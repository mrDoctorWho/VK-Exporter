#!/usr/bin/env python2
# coding: utf-8

# based on the vk4xmpp gateway, v2.25
# © simpleApps, 2013 — 2014.
# Program published under MIT license.

import gc
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import urllib

core = getattr(sys.modules["__main__"], "__file__", None)
if core:
	core = os.path.abspath(core)
	root = os.path.dirname(core)
	if root:
		os.chdir(root)

sys.path.insert(0, "library")
reload(sys).setdefaultencoding("utf-8")

from datetime import datetime
from webtools import *
from writer import *
from stext import *
from stext import _

setVars("ru", root)

Semaphore = threading.Semaphore()

LOG_LEVEL = logging.DEBUG

EXTENSIONS = []
MAXIMUM_FORWARD_DEPTH = 100

pidFile = "pidFile.txt"
logFile = "vk4xmpp.log"
crashDir = "crash"
PhotoSize = "photo_100"


logger = logging.getLogger("vk4xmpp")
logger.setLevel(LOG_LEVEL)
loggerHandler = logging.FileHandler(logFile)
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s %(message)s",
				"[%d.%m.%Y %H:%M:%S]")
loggerHandler.setFormatter(formatter)
logger.addHandler(loggerHandler)

import vkapi as api

## Escaping xmpp non-allowed chars
badChars = [x for x in xrange(32) if x not in (9, 10, 13)] + [57003, 65535]
escape = re.compile("|".join(unichr(x) for x in badChars), re.IGNORECASE | re.UNICODE | re.DOTALL).sub
sortMsg = lambda msgOne, msgTwo: msgOne.get("mid", 0) - msgTwo.get("mid", 0)
require = lambda name: os.path.exists("extensions/%s.py" % name)

def registerHandler(type, handler):
	EXTENSIONS.append(handler)


def loadExtensions(dir):
	"""
	Read and exec files located in dir
	"""
	for file in os.listdir(dir):
		if not file.startswith("."):
			execfile("%s/%s" % (dir, file), globals())


def execute(handler, list=()):
	try:
		result = handler(*list)
	except SystemExit:
		result = 1
	except Exception:
		result = -1
		crashLog(handler.func_name)
	return result


def apply(instance, args=()):
	try:
		code = instance(*args)
	except Exception:
		code = None
	return code


def runThread(func, args=(), name=None):
	thr = threading.Thread(target=execute, args=(func, args), name=name or func.func_name)
	try:
		thr.start()
	except threading.ThreadError:
		crashlog("runThread.%s" % name)


class VK(object):
	"""
	The base class containts most of functions to work with VK
	"""
	def __init__(self):
		self.online = False
		self.userID = 0
		self.friends_fields = set(["screen_name"])
		logger.debug("VK.__init__")

	getToken = lambda self: self.engine.token

	def checkData(self):
		"""
		Checks the token or authorizes by password
		Raises api.TokenError if token is invalid or missed in hell
		Raises api.VkApiError if phone/password is invalid
		"""
		logger.debug("VK: checking data")

		if self.engine.token:
			logger.debug("VK.checkData: trying to use token")
			if not self.checkToken():
				logger.error("VK.checkData: token invalid: %s" % self.engine.token)
				raise api.TokenError("Token is invalid: %s" % (self.engine.token))
		else:
			raise api.TokenError("%s, Where the hell is your token?" % self.source)

	def checkToken(self):
		"""
		Checks the api token
		"""
		try:
			int(self.method("isAppUser", force=True))
		except (api.VkApiError, TypeError):
			return False
		return True

	def auth(self, token=None, raise_exc=False):
		"""
		Initializes self.engine object
		Calls self.checkData() and initializes longPoll if all is ok
		"""
		logger.debug("VK.auth %s token" % ("with" if token else "without"))
		self.engine = api.APIBinding(token=token)
		try:
			self.checkData()
		except api.AuthError as e:
			logger.error("VK.auth failed with error %s" % (e.message))
			if raise_exc:
				raise
			return False
		except Exception:
			crashLog("VK.auth")
			return False
		logger.debug("VK.auth completed")
		self.online = True
		return True

	def method(self, method, args=None, nodecode=False, force=False):
		"""
		This is a duplicate function of self.engine.method
		Needed to handle errors properly exactly in __main__
		Parameters:
			method: obviously VK API method
			args: method aruments
			nodecode: decode flag (make json.loads or not)
			force: says that method will be executed even the captcha and not online
		See library/vkapi.py for more information about exceptions
		Returns method result
		"""
		args = args or {}
		result = {}
		if not self.engine.captcha and (self.online or force):
			try:
				result = self.engine.method(method, args, nodecode)
			except api.InternalServerError as e:
				logger.error("VK: internal server error occurred while executing method(%s) (%s)" % (method, e.message))

			except api.NetworkNotFound:
				logger.critical("VK: network is unavailable. Is vk down or you have network problems?")
				self.online = False

			except api.VkApiError as e:
				logger.error("VK: apiError %s" % (e.message))
				self.online = False
		return result

	def disconnect(self):
		"""
		Stops all user handlers and removes himself from Poll
		"""
		logger.debug("VK: user has left")
		self.online = False
		runThread(self.method, ("account.setOffline", None, True, True))

	def getFriends(self, fields=None):
		"""
		Executes friends.get and formats it in key-values style
		Example: {1: {"name": "Pavel Durov", "online": False}
		Parameter fields is needed to receive advanced fields which will be added in result values
		"""
		fields = fields or self.friends_fields
		raw = self.method("friends.get", {"fields": str.join(chr(44), fields)}) or ()
		friends = {}
		for friend in raw:
			uid = friend["uid"]
			online = friend["online"]
			name = escape("", str.join(chr(32), (friend["first_name"], friend["last_name"])))
			friends[uid] = {"name": name, "online": online}
			for key in fields:
				if key != "screen_name": # screen_name is default
					friends[uid][key] = friend.get(key)
		return friends

	def getMessages(self, count=5, mid=0):
		"""
		Gets last messages list count 5 with last id mid
		"""
		values = {"out": 0, "filters": 1, "count": count}
		if mid:
			del values["count"], values["filters"]
			values["last_message_id"] = mid
		return self.method("messages.get", values)

	def getUserID(self):
		"""
		Gets user id and adds his id into jidToID
		"""
		self.userID = self.method("execute.getUserID")
		return self.userID

	def getUserData(self, uid, fields=None):
		"""
		Gets user data. Such as name, photo, etc
		Will request method users.get
		Default fields is ["screen_name"]
		"""
		if not fields:
			fields = self.friends_fields
		data = self.method("users.get", {"fields": ",".join(fields), "user_ids": uid}) or {}
		if not data:
			data = {"name": "None"}
			for key in fields:
				data[key] = "None"
		else:
			data = data.pop()
			data["name"] = escape("", str.join(chr(32), (data.pop("first_name"), data.pop("last_name"))))
		return data

	def getMessageHistory(self, count, uid, rev=0, start=0):
		"""
		Gets messages history
		"""
		values = {"count": count, "user_id": uid, "rev": rev, "start": start}
		return self.method("messages.getHistory", values)


format = "[%(date)s] <%(name)s> %(body)s\n"

if not os.path.exists("logs"):
	os.makedirs("logs")
loadExtensions("extensions")

# https://oauth.vk.com/authorize?scope=69638&redirect_uri=https%3A%2F%2Foauth.vk.com%2Fblank.html&display=mobile&client_id=3789129&response_type=token
print "\nYou can get token over there: http://jabberon.ru/vk4xmpp.html"
token = raw_input("\nToken: ")

class User:
	"""
	A compatibility layer for vk4xmpp-extensions
	"""
	vk = VK()

user = User()
user.vk.auth(token)
user.vk.friends = user.vk.getFriends()

for friend in user.vk.friends.keys():
	file = open("logs/%d.txt" % friend, "w")
	start = 0
	while True:
		count = 200
		rev = 0
		messages = sorted(user.vk.getMessageHistory(count, friend, rev, start)[1:], sortMsg)
		print "receiving messages for %d" % friend
		if not messages or not messages[0]:
			print "no messages for %d" % friend
			file.close()
			os.remove("logs/%d.txt" % friend)
			break
		last = messages[0]["mid"]
		if last == start:
			start = 0
			break
		start = last
		for message in messages:
			body = uHTML(message["body"])
			iter = EXTENSIONS.__iter__()
			for func in iter:
				try:
					result = func(user, message)
				except Exception:
					result = None
					crashLog("handle.%s" % func.__name__)
				if result is None:
					for func in iter:
						apply(func, (user, message))
					break
				else:
					body += result
			date = datetime.fromtimestamp(message["date"]).strftime("%d.%m.%Y %H:%M:%S")
			name = user.vk.getUserData(message["from_id"])["name"]
			file.write(format % vars())
print "Done. Check out the \"logs\" directory"