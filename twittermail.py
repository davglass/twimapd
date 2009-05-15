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
from tempfile import NamedTemporaryFile
from pysqlite2 import dbapi2 as sqlite



from cStringIO import StringIO

MAILBOXDELIMITER = "."
boxes = {
    'Inbox': None,
    #'Sent': None,
    #'Mentions': None,
    #'Directs': None
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

file_map = {}


def saveMbox(conn, folder, data):
    print "Saving: %s" % folder
    cursor = conn.cursor()
    for i in data:
        cursor.execute("insert into messages (id, folder, seen, message) values (?, ?, 1, ?)", (i.id, folder, i.AsJsonString()))
    conn.commit()

class TwitterUserAccount(object):
  implements(imap4.IAccount)

  def __init__(self, cache):
    self.cache = cache
    self.user = cache.get('api').GetUser(cache.get('username'))
    self.cache.set('user', self.user)
    

    for i in boxes:
        if i == 'Inbox':
            saveMbox(self.cache.get('conn'), 'Inbox', self.cache.get('api').GetFriendsTimeline())
        elif i == 'Sent':
            saveMbox(self.cache.get('conn'), 'Sent', self.cache.get('api').GetUserTimeline())
        elif i == 'Mentions':
            saveMbox(self.cache.get('conn'), 'Mentions', self.cache.get('api').GetReplies())
        elif i == 'Directs':
            saveMbox(self.cache.get('conn'), 'Directs', self.cache.get('api').GetDirectMessages())

  def listMailboxes(self, ref, wildcard):
    mail_boxes = []
    for i in boxes_order:
        boxes[i] = TwitterImapMailbox(i, self.cache)
        mail_boxes.append((i, boxes[i]))

    return mail_boxes

  def select(self, path, rw=True):
    print "Select: %s" % path
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
    self.conn = self.cache.get('conn')

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
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s")' % self.folder)
        row = cur.fetchone()
        return row[0]
        #return len(boxes_data[self.folder])

  def getRecentCount(self):
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s") and (seen = 1)' % self.folder)
        row = cur.fetchone()
        return row[0]
        #return len(boxes_data[self.folder])

  def getUnseenCount(self):
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s") and (seen = 1)' % self.folder)
        row = cur.fetchone()
        return row[0]
        #return len(boxes_data[self.folder])

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
    cur = self.conn.cursor()
    cur.execute('select message from messages where (folder = "%s")' % self.folder)
    counter = 0
    for i in cur:
        counter += 1
        msg = simplejson.loads(i[0])
        print "ID: %s" % msg['id']
        yield counter, TwitterImapMessage(simplejson.loads(i[0]), self.cache)
        


    """
    counter = 0
    if self.folder in boxes_data:
        if uid:
            for id in messages:
                yield 1, id_map[id]
        else:
            for i in boxes_data[self.folder]:
                counter += 1
                print "FETCHING %s :: %s :: %s" % (counter, i.id, i)
                i.folder = self.folder
                id_map[i.id] = TwitterImapMessage(i, self.cache)
                yield counter, id_map[i.id]
    else:
        raise imap4.MailboxException("Not implemented")
    """

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
    self.id = info['id']
    self.cache = cache
    
    """
    conn = self.cache.get('conn')
    cur = conn.cursor()
    
    cur.execute('select * from messages where (folder = "%s") and (id = %s)' % (self.info.folder, self.id))
    row = cur.fetchone()
    if not row:
        temp = open("/tmp/twimap_%s.status" % self.id, 'w')
        temp.write(self.info.text.encode("utf-8"))
        temp.close()

        cur.execute('insert into messages (id, message, folder) values (?, ?, ?)', (self.id, self.info.text.encode("utf-8"), self.info.folder))
        conn.commit()

    file_map[self.id] = "/tmp/twimap_%s.status" % self.id
    """
    
  def getUID(self):
    return self.id
    
  def getFlags(self):
    print 'FLAGS:'
    flags = []
    #flags.append("\Seen")
    if self.info['favorited']:
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
    #return rfc822date(time.localtime(self.info['created_at_in_seconds']))
    return rfc822date(time.localtime())
    
  def getHeaders(self, negate, *names):
    try:
        user_name = self.info['recipient_screen_name']
    except KeyError:
        user_name = self.user.name

    uname = self.cache.get('username')

    try:
        sender_name = self.info['sender_screen_name']
        sname = self.info['sender_screen_name']
    except KeyError:
        sender_name = self.info['user']['screen_name']
        sname = self.info['user']['name']

    headers = [
        "To: %s <%s@twitter.com>" % (user_name, uname),
        "Envelope-To: %s@twitter.com" % uname,
        "Return-Path: %s@twitter.com" % sender_name, 
        "From: %s <%s@twitter.com>" % (sname, sender_name),
        "Delivery-Date: %s" % self.info['created_at'], 
        "Date: %s" % self.info['created_at'], 
        "Subject: %s" % self.info['text'].encode("utf-8"),
        "Message-ID: <%s@twitter.com>" % self.info['id'],
        "Content-Type: text/plain",
        "Mime-Version: 1.0",
        "X-TwIMAP-ID: %s" % self.info['id'],
        "X-TwIMAP-USER: http://twitter.com/%s" % sender_name,
        "X-TwIMAP-URL: http://twitter.com/%s/status/%s" % (sender_name, self.info['id'])
    ]
    
    if 'in_reply_to_status_id' in self.info:
        headers.append("References: <%s@twitter.com>" % self.info['in_reply_to_status_id'])
        headers.append("In-Reply-To: <%s@twitter.com>" % self.info['in_reply_to_status_id'])

    if 'favorited' in self.info:
        headers.append("X-TwIMAP-FAVORITED: yes")

    rawheaders = "\n".join(headers)


    conn = self.cache.get('conn')
    cur = conn.cursor()
    cur.execute('update messages set headers=? where (id = ?)', (rawheaders, self.id))
    conn.commit()
    
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
    return file(file_map[self.id])
    
  def getSize(self):
    return len(self.info['text'])
    
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
        try:
            file = open("/tmp/%s_twimap.db" % credentials.username)
        except IOError:
            createDB = True
        else:
            createDB = False

        conn = sqlite.connect("/tmp/%s_twimap.db" % credentials.username)
        cur = conn.cursor()
        if createDB:
            sql = "create table log (key text, value text)"
            cur.execute(sql)
            sql = "create table messages (id integer, folder text, headers text, seen integer, message text)"
            cur.execute(sql)

        cur.execute('delete from log where key = "lastcheck"')
        sql = 'insert into log (key, value) values ("lastcheck", "%s")' % rfc822date(time.localtime())
        print "SQL :: %s" % sql
        cur.execute(sql)
        conn.commit()
        self.cache.set('conn', conn)
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

