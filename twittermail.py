from twisted.internet import reactor
from twisted.mail import imap4
from twisted.mail.smtp import rfc822date
from zope.interface import implements
from twisted.internet import reactor, defer, protocol

from twisted.cred import checkers, credentials, error as credError
import simplejson, base64, urllib2, sys, re, twitter, time
from urlparse import urlparse
from urllib2 import HTTPError
from email.parser import Parser



from cStringIO import StringIO

MAILBOXDELIMITER = "."
boxes = {
    'Inbox': None,
    'Sent': None,
    'Mentions': None,
    'Directs': None
}

boxes_order = ['Inbox', 'Sent', 'Mentions', 'Directs']

_statusRequestDict = {
    'MESSAGES': 'getMessageCount',
    'RECENT': 'getRecentCount',
    'UIDNEXT': 'getUIDNext',
    'UIDVALIDITY': 'getUIDValidity',
    'UNSEEN': 'getUnseenCount'
}
boxes_data = {}

id_map = {}


class TwitterUserAccount(object):
  implements(imap4.IAccount)

  def __init__(self, cache):
    self.cache = cache
    self.user = cache.get('api').GetUser(cache.get('username'))
    self.cache.set('user', self.user)
    for i in boxes:
        boxes[i] = TwitterImapMailbox(i, self.cache)

  def listMailboxes(self, ref, wildcard):
    mail_boxes = []
    for i in boxes_order:
        mailbox = boxes[i]
        mail_boxes.append((i, mailbox))

    return mail_boxes

  def select(self, path, rw=True):
    return boxes[path]

  def create(self, path):
    return True

  def delete(self, path):
    return True

  def rename(self, oldname, newname):
    return True

  def isSubscribed(self, path):
    return True

  def subscribe(self, path):
    return True

  def unsubscribe(self, path):
    return True

class TwitterImapMailbox(object):
  implements(imap4.IMailbox)

  def __init__(self, folder, cache):
    print "Fetching: %s" % folder
    print "Using: %s" % cache.get('api')
    self.folder = folder
    self.cache = cache
    self.api = cache.get('api')
    self.data = self.api
    self.listeners = []

    
    if folder == 'Inbox':
        boxes_data[folder] = self.api.GetFriendsTimeline()
    elif folder == 'Sent':
        boxes_data[folder] = self.api.GetUserTimeline()
    elif folder == 'Mentions':
        boxes_data[folder] = self.api.GetReplies()
    elif folder == 'Directs':
        boxes_data[folder] = self.api.GetDirectMessages()
    
    print "DATA :: %s" % boxes_data

    if folder in boxes_data:
        print "LENGTH:: %s" % len(boxes_data[folder])

  def getHierarchicalDelimiter(self):
    return MAILBOXDELIMITER

  def getFlags(self):
    flags = ['\Seen', '\Unseen', '\Flagged', '\Answered']
    flags.append('\HasNoChildren')
    return flags

  def getMessageCount(self):
        return len(boxes_data[self.folder])

  def getRecentCount(self):
        return len(boxes_data[self.folder])

  def getUnseenCount(self):
        return len(boxes_data[self.folder])

  def isWriteable(self):
    return True

  def getUIDValidity(self):
    return 1

  def getUID(self, messageNum):
    raise imap4.MailboxException("Not implemented")

  def getUIDNext(self):
    return 1

  def fetch(self, messages, uid):
    print "FETCH :: %s :: %s" % (messages, uid)
    counter = 0
    if self.folder in boxes_data:
        if uid:
            for id in messages:
                yield 1, id_map[id]
        else:
            for i in boxes_data[self.folder]:
                counter += 1
                print "FETCHING %s :: %s :: %s" % (counter, i.id, i)
                id_map[i.id] = TwitterImapMessage(i, self.cache)
                yield counter, id_map[i.id]
    else:
        raise imap4.MailboxException("Not implemented")

  def addListener(self, listener):
    self.listeners.append(listener)
    return True

  def removeListener(self, listener):
    self.listeners.remove(listener)
    return True

  def requestStatus(self, names):
    r = {}
    for n in names:
        r[n] = getattr(self, _statusRequestDict[n.upper()])()
    return r

  def addMessage(self, msg, flags=None, date=None):
    raise imap4.MailboxException("Not implemented")

  def store(self, messageSet, flags, mode, uid):
    print "Store: %s :: %s :: %s" % (messageSet, mode, uid)
    raise imap4.MailboxException("Not implemented")

  def expunge(self):
    raise imap4.MailboxException("Not implemented")

  def destroy(self):
    raise imap4.MailboxException("Not implemented")
    
class TwitterImapMessage(object):
  implements(imap4.IMessage)
  
  def __init__(self, info, cache):
    print "MESSAGE: %s" % info
    self.user = cache.get('user')
    self.info = info
    self.id = info.id
    self.cache = cache
    
    
  def getUID(self):
    return self.id
    
  def getFlags(self):
    print 'FLAGS:'
    flags = []
    #flags.append("\Seen")
    if self.info.favorited:
        flags.append("\Flagged")


    """
    if self.info["flags"]["isRead"]:
      flags.append("\Seen")
    if self.info["flags"]["isReplied"]:
      flags.append("\Answered")
    if self.info["flags"]["isFlagged"]:
      flags.append("\Flagged")
    if self.info["flags"]["isDraft"]:
      flags.append("\Draft")
    """
    return flags
    
  def getInternalDate(self):
    return rfc822date(time.localtime(self.info.created_at_in_seconds))
    
  def getHeaders(self, negate, *names):
    try:
        user_name = self.info.recipient_screen_name
    except AttributeError:
        user_name = self.user.name

    uname = self.cache.get('username')

    try:
        sender_name = self.info.sender_screen_name
        sname = self.info.sender_screen_name
    except AttributeError:
        sender_name = self.info.user.screen_name
        sname = self.info.user.name

    headers = [
        "To: %s <%s@twitter.com>" % (user_name, uname),
        "Envelope-To: %s@twitter.com" % uname,
        "Return-Path: %s@twitter.com" % sender_name, 
        "From: %s <%s@twitter.com>" % (sname, sender_name),
        "Delivery-Date: %s" % self.info.created_at, 
        "Date: %s" % self.info.created_at, 
        "Subject: %s" % self.info.text.encode("utf-8"),
        "Message-ID: <%s@twitter.com>" % self.info.id,
        "Content-Type: text/plain",
        "Mime-Version: 1.0",
        "X-TwIMAP-ID: %s" % self.info.id,
        "X-TwIMAP-USER: http://twitter.com/%s" % sender_name,
        "X-TwIMAP-URL: http://twitter.com/%s/status/%s" % (sender_name, self.info.id)
    ]
    
    if self.info.in_reply_to_status_id:
        headers.append("References: <%s@twitter.com>" % self.info.in_reply_to_status_id)
        headers.append("In-Reply-To: <%s@twitter.com>" % self.info.in_reply_to_status_id)

    if self.info.favorited:
        headers.append("X-TwIMAP-FAVORITED: yes")

    rawheaders = "\n".join(headers)


    parser = Parser()
    try:
        message = parser.parsestr(rawheaders, True)
    except UnicodeEncodeError:
        headers[7] = 'Subject: Failed to parse subject'
        rawheaders = "\n".join(headers)
        message = parser.parsestr(rawheaders, True)
    
    headerDict = {}
    for (name, value) in message.items():
      headerDict[name.lower()] = value

    print "HEADERS: %s" % headerDict

    return headerDict
    
  def getBodyFile(self):
    return StringIO(self.info.text.encode("utf-8"))
    
  def getSize(self):
    return len(self.info.text)
    
  def isMultipart(self):
    return False
    
  def getSubPart(self, part):
    print "SUBPART:: %s" % part
    raise imap4.MailboxException("getSubPart not implemented")



class TwitterCredentialsChecker():
  implements(checkers.ICredentialsChecker)
  credentialInterfaces = (credentials.IUsernamePassword,)

  def __init__(self, cache):
    self.cache = cache

  def requestAvatarId(self, credentials):
    api = twitter.Api(username=credentials.username, password=credentials.password)
    self.cache.set('api', api)
    self.cache.set('username', credentials.username)
    try:
        user = api.GetDirectMessages()
        return defer.succeed(credentials.username)
    except HTTPError:
      return defer.fail(credError.UnauthorizedLogin("Bad password - fool"))


class ObjCache(object):
  def __init__(self):
    self.cache = {}

  def get(self, item):
    return self.cache[item]

  def set(self, item, value):
    self.cache[item] = value

