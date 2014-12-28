# coding: utf-8
# This file is a part of VK4XMPP Transport
# © simpleApps, 2014.
# This plugin contain all vk4xmpp plugin's API features
# Rename it to "example.py" if you wanna test it
# Please notice that plugins are working in globals() so names must be unique


def msg01_handler(user, message):
	"""
	Linear handler.
	Called for each message has been received from VK
	Parameters:
		user: User class object
		message: single message json object
	Return values:
		None: the function itself should send a message
		str type: transport's core will add returned string to existing body
	"""
	return "\nmsg01_handler is awesome"

registerHandler("msg01", msg01_handler)

## Oops!