from twisted.mail import imap4, maildir
from twisted.internet import reactor, defer, protocol
from twisted.cred import portal, checkers, credentials
from twisted.cred import error as credError
from twisted.python import filepath
from zope.interface import implements
import time, os, random, pickle

from twittermail import TwitterUserAccount, TwitterImapMailbox, TwitterCredentialsChecker, ObjCache

import email

class MailUserRealm(object):
  implements(portal.IRealm)
  avatarInterfaces = {
    imap4.IAccount: TwitterUserAccount,
    }

  def __init__(self, cache):
    self.cache = cache

  def requestAvatar(self, avatarId, mind, *interfaces):
    for requestedInterface in interfaces:
      if self.avatarInterfaces.has_key(requestedInterface):
        # return an instance of the correct class
        avatarClass = self.avatarInterfaces[requestedInterface]
        avatar = avatarClass(self.cache)
        # null logout function: take no arguments and do nothing
        logout = lambda: None
        return defer.succeed((requestedInterface, avatar, logout))

    # none of the requested interfaces was supported
    raise KeyError("None of the requested interfaces is supported")

class IMAPServerProtocol(imap4.IMAP4Server):
  "Subclass of imap4.IMAP4Server that adds debugging."
  debug = True

  def lineReceived(self, line):
    if self.debug:
      print "CLIENT:", line
    imap4.IMAP4Server.lineReceived(self, line)

  def sendLine(self, line):
    imap4.IMAP4Server.sendLine(self, line)
    if self.debug:
      print "SERVER:", line

class IMAPFactory(protocol.Factory):
  protocol = IMAPServerProtocol
  portal = None # placeholder

  def buildProtocol(self, address):
    p = self.protocol()
    p.portal = self.portal
    p.factory = self
    return p

if __name__ == "__main__":
    
    cache = ObjCache()

    portal = portal.Portal(MailUserRealm(cache))
    portal.registerChecker(TwitterCredentialsChecker(cache))

    factory = IMAPFactory()
    factory.portal = portal

    reactor.listenTCP(1143, factory)
    reactor.run()


