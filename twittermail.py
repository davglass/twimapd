import simplejson, base64, urllib2, sys, re, twitter, time

from twisted.internet import reactor
from twisted.mail import imap4
from twisted.mail.smtp import rfc822date
from zope.interface import implements
from twisted.internet import reactor, defer, protocol
from twisted.cred import checkers, credentials, error as credError
from urlparse import urlparse
from urllib2 import HTTPError
from email.parser import Parser
from pysqlite2 import dbapi2 as sqlite
from cStringIO import StringIO


MAILBOXDELIMITER = "."
boxes = {
    'Inbox': None,
    'Sent': None,
    'Mentions': None,
    'Directs': None
}

boxes_order = [
    'Inbox',
    'Sent', 
    'Mentions', 
    'Directs'
]

_statusRequestDict = {
    'MESSAGES': 'getMessageCount',
    'RECENT': 'getRecentCount',
    'UIDNEXT': 'getUIDNext',
    'UIDVALIDITY': 'getUIDValidity',
    'UNSEEN': 'getUnseenCount'
}

id_map = {}

def saveMbox(cur, folder, data):
    print "Saving: %s" % folder
    for i in data:
        cur.execute("insert or ignore into messages (id, folder, message) values (?, ?, ?)", (i.id, folder, i.AsJsonString().encode('utf-8')))
            
    if folder == 'Sent':
        #Mark all messages in Sent as Read (since you sent them)
        cur.execute("update messages set seen = 1 where (folder = 'Sent')")

class TwitterUserAccount(object):
  implements(imap4.IAccount)

  def __init__(self, cache):
    print "USER ACCOUNT"
    self.cache = cache
    self.user = cache.get('api').GetUser(cache.get('username'))
    self.cache.set('user', self.user)
    self.conn = self.cache.get('conn')
    

  def listMailboxes(self, ref, wildcard):
    mail_boxes = []
    for i in boxes_order:
        boxes[i] = TwitterImapMailbox(i, self.cache)
        mail_boxes.append((i, boxes[i]))
    
    cur = self.conn.cursor()
    cur.execute('select value from log where (key = "folder") order by value')
    for row in cur:
        boxes[row[0]] = TwitterImapMailbox(row[0], self.cache)
        mail_boxes.append((i, boxes[i]))

    return mail_boxes

  def select(self, path, rw=True):
    print "Select: %s" % path
    if path == 'INBOX':
        path = 'Inbox'
    return TwitterImapMailbox(path, self.cache)

  def close(self):
    return True

  def create(self, path):
    return False
    cur = self.conn.cursor()
    cur.execute('insert into log (key, value) values (?, ?)', ('folder', path))
    self.conn.commit()
    return True

  def delete(self, path):
    return False

  def rename(self, oldname, newname):
    return False

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

    cur = self.conn.cursor()
    if self.folder == 'Inbox':
        saveMbox(cur, 'Inbox', self.cache.get('api').GetFriendsTimeline())
    elif self.folder == 'Sent':
        saveMbox(cur, 'Sent', self.cache.get('api').GetUserTimeline())
    elif self.folder == 'Mentions':
        saveMbox(cur, 'Mentions', self.cache.get('api').GetReplies())
    elif self.folder == 'Directs':
        saveMbox(cur, 'Directs', self.cache.get('api').GetDirectMessages())

    """
    if self.folder[0:1] == '#':
        url = "http://search.twitter.com/search.json?q=%s" % self.folder.replace('#', '%23')
        print "Search: %s" % url
        json = self.api._FetchUrl(url)
        data = simplejson.loads(json)
        print "Data: %s" % data
        items = []
        for i in data['results']:
            items.append(twitter.Status.NewFromJsonDict(i))
        print items
        #Duplicate ID's??
        #saveMbox(cur, self.folder, items)
    """
    self.conn.commit()

  def getHierarchicalDelimiter(self):
    return MAILBOXDELIMITER

  def getFlags(self):
    flags = ['\Seen', '\Unseen', '\Flagged', '\Answered']
    flags.append('\HasNoChildren')
    return flags

  def getMessageCount(self):
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s")' % self.folder)
        row = cur.fetchall()[0]
        print "getMessageCount :: %s :: %s" % (self.folder, row[0])
        return row[0]

  def getRecentCount(self):
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s") and (seen != 1)' % self.folder)
        row = cur.fetchall()[0]
        print "getRecentCount :: %s :: %s" % (self.folder, row[0])
        return row[0]

  def getUnseenCount(self):
        cur = self.conn.cursor()
        cur.execute('select count(*) from messages where (folder = "%s") and (seen != 1)' % self.folder)
        row = cur.fetchall()[0]
        print "getUnseenCount :: %s :: %s" % (self.folder, row[0])
        return row[0]

  def isWriteable(self):
    return True

  def getUIDValidity(self):
    return 0

  def getUID(self, messageNum):
    raise imap4.MailboxException("Not implemented")

  def getUIDNext(self):
    return 1

  def fetch(self, messages, uid):
    print "FETCH :: %s :: %s :: %s" % (self.folder, messages, uid)
    cur = self.conn.cursor()

    sql = 'select message, seen from messages where (folder = "%s") order by id' % self.folder
    try:
        if uid:
            uid = len(messages)
    except TypeError:
        uid = False

    if uid:
        ids = []
        for id in messages:
            ids.append("%s" % id_map[id])
        sql = 'select message, seen from messages where (folder = "%s") and (id in (%s))' % (self.folder, ','.join(ids))

    print "SQL: %s" % sql
    cur.execute(sql)
    counter = 0
    for i in cur:
        counter += 1
        msg = simplejson.loads(i[0])
        msg['counter'] = counter
        msg['seen'] = i[1]
        if self.folder == 'Directs':
            msg['favorited'] = False
        id_map[counter] = msg['id']
        #print "ID: %s :: %s" % (counter, msg['id'])
        mail = TwitterImapMessage(msg, self.cache)
        yield counter, mail
        

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
    print "STORE: %s :: %s :: %s :: %s" % (messageSet, flags, mode, uid)
    cur = self.conn.cursor()
    for i in messageSet:
        if '\Flagged' in flags:
            url = 'http://twitter.com/favorites/create/%s.json' % id_map[i]
            if mode == -1:
                url = 'http://twitter.com/favorites/destroy/%s.json' % id_map[i]
            json = self.api._FetchUrl(url, post_data={})
            data = simplejson.loads(json)
            status = twitter.Status.NewFromJsonDict(data)
            cur.execute("update messages set message = ? where (id = ?)", (status.AsJsonString().encode('utf-8'), id_map[i]))

        if '\Seen' in flags:
            seen = 1
            if mode == -1:
                seen = 0
            sql = "update messages set seen = %s where (id = %s)" % (seen, id_map[i])
            print "SQL :: %s" % sql
            cur.execute(sql)

        if '\Deleted' in flags:
            deleted = 1
            if mode == -1:
                deleted = 0
            sql = "update messages set deleted = %s where (id = %s)" % (deleted, id_map[i])
            print "SQL :: %s" % sql
            cur.execute(sql)

    self.conn.commit()

  def expunge(self):
    cur = self.conn.cursor()
    sql = "delete from messages where (deleted = 1)"
    print "SQL :: %s" % sql
    cur.execute(sql)
    self.conn.commit()

  def destroy(self):
    raise imap4.MailboxException("Not implemented")
    
class TwitterImapMessage(object):
  implements(imap4.IMessage)
  
  def __init__(self, info, cache):
    #print "MESSAGE: %s" % info
    self.user = cache.get('user')
    self.info = info
    self.id = info['id']
    self.cache = cache
    
  def getUID(self):
    #return self.id
    return self.info['counter']
    
  def getFlags(self):
    #print 'FLAGS:'
    flags = []
    if self.info['seen']:
        flags.append("\Seen")

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
    #print "getInternalDate :: %s" % self.info
    #return rfc822date(time.localtime(self.info['created_at_in_seconds']))
    return self.info['created_at']
    
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
    
    headers = {
        "to": "%s <%s@twitter.com>" % (user_name, uname),
        "envelope-to": "%s@twitter.com" % uname,
        "return-path": "%s@twitter.com" % sender_name, 
        "from": "%s <%s@twitter.com>" % (sname, sender_name),
        "delivery-date": "%s" % self.info['created_at'], 
        "date": "%s" % self.info['created_at'], 
        "subject": "%s" % self.info['text'],
        "message-id": "<%s@twitter.com>" % self.info['id'],
        "content-type": 'text/plain; charset="UTF-8"',
        "content-transfer-encoding": "quoted-printable",
        "mime-version": "1.0",
        "x-twimap-id": "%s" % self.info['id'],
        "x-twimap-user": "http://twitter.com/%s" % sender_name,
        "x-twimap-url": "http://twitter.com/%s/status/%s" % (sender_name, self.info['id'])
    }

    if 'in_reply_to_status_id' in self.info:
        headers["references"] = "<%s@twitter.com>" % self.info['in_reply_to_status_id']
        headers["in-reply-to"] = "<%s@twitter.com>" % self.info['in_reply_to_status_id']

    if self.info['favorited']:
        headers["x-twimap-favorited"] = "yes"

    for i in headers:
        headers[i] = headers[i].encode('utf-8', 'replace')

    return headers
    
  def getBodyFile(self):
    txt = self.info['text'].encode("utf-8")
    return StringIO(txt)
    
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
    api = twitter.Api(username=credentials.username, password=credentials.password, input_encoding=None, request_headers={
        'X-Twitter-Client': 'twIMAPd',
        'X-Twitter-Client-Version': '.5'
    })
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
            sql = "create table messages (id integer primary key, folder text, headers text, seen integer default 0, deleted integer default 0, message text)"
            cur.execute(sql)

        cur.execute('delete from log where (key = "lastcheck")')
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

