import datetime

import frappe
import phonenumbers
import pytz
import requests
from frappe import enqueue

wa_settings = frappe.get_doc("WhatsApp Settings")
# ULTRAMSG_API = wa_settings.api_url
ULTRAMSG_API = wa_settings.api_url.rstrip("/")
ULTRAMSG_INSTANCE = wa_settings.instance_id
ULTRAMSG_TOKEN = wa_settings.token
TIMEZONE = frappe.db.get_single_value("System Settings", "time_zone")

# constants.py (new file OR top of your existing file)
MESSAGE_FROM_CLIENT = "Message from Client"
MESSAGE_TO_SUPPORT = "Message to Support"
REPLY_FROM_SUPPORT = "Reply from Support"
REPLY_TO_CLIENT = "Reply to Client"
UNIDENTIFIED_MESSAGE = "Unidentified Message"

INCLUDE_SENDER_DETAILS = True
MESSAGE_ID_TAG = "*Message ID:* "


class IncomingMessage:
	msg_id: str
	msg_sender: str
	message_body: str
	msg_receiver: str
	author: str
	timestamp: int
	from_me: bool
	media: dict
	ack_status: int
	type: str
	file_name: str
	is_forwarded: bool
	is_mentioned: bool
	quoted_message: dict
	quoted_message_id: str
	message_type: str

	def __init__(self, message_data: dict):
		self.msg_id = message_data.get("id")
		self.msg_sender = message_data.get("from")
		self.message_body = message_data.get("body")
		self.msg_receiver = message_data.get("to")
		self.author = message_data.get("author")
		self.timestamp = message_data.get("time")
		self.from_me = message_data.get("fromMe")
		self.media = message_data.get("media")
		self.ack_status = message_data.get("ack")
		self.type = message_data.get("type")
		self.file_name = message_data.get("filename")
		self.is_forwarded = message_data.get("isforwarded")
		self.is_mentioned = message_data.get("ismentioned")
		self.quoted_message = message_data.get("quotedMsg")
		self.quoted_message_id = message_data.get("quotedMsg", {}).get("id", None)
		self.message_type = UNIDENTIFIED_MESSAGE

	def __repr__(self):
		return f"<IncomingMessage id='{self.msg_id}' from='{self.msg_sender}'>"


def parse_incoming_message(data):
	message_data = frappe.parse_json(data)
	return IncomingMessage(message_data)


@frappe.whitelist(allow_guest=True)
def handle_incoming_webhook(data=None):
	incoming_message = parse_incoming_message(data)

	sender_contact = get_contact_from_ultramsg(incoming_message.msg_sender)

	create_contact(
		contact=sender_contact
	)  # if some unkown person sent a message, create a contact in database
	frappe.db.commit()  # Commit changes, as the contact should be commit before use

	is_message_from_client_group = in_client_group(incoming_message.msg_sender)
	is_message_from_support_group = in_support_group(incoming_message.msg_sender)

	# if message is received from a group in client group mapping
	if not incoming_message.from_me and is_message_from_client_group and not is_message_from_support_group:
		on_receive_from_client_group(incoming_message)
	elif not incoming_message.from_me and not is_message_from_client_group and is_message_from_support_group:
		on_receive_from_support_group(incoming_message)
	elif incoming_message.from_me and in_support_group(incoming_message.msg_receiver):
		on_forward_to_support_group(incoming_message)
	elif incoming_message.from_me and in_client_group(incoming_message.msg_receiver):
		on_forward_to_client_group(incoming_message)
	# if not incoming_message.from_me and not in_managers(msg_sender=incoming_message.msg_sender):
	#     on_receive_message(incoming_message)
	# elif not incoming_message.from_me and in_managers(msg_sender=incoming_message.msg_sender):
	#     on_REPLY_FROM_SUPPORT(incoming_message)
	# elif incoming_message.from_me and in_managers(msg_sender=incoming_message.msg_receiver):
	#     on_forward_to_managers(incoming_message)
	# elif incoming_message.from_me and not in_managers(msg_sender=incoming_message.msg_receiver):
	#     on_reply_to_client(incoming_message)
	else:
		on_unidentified_message(incoming_message)

	return {"status": "success"}


@frappe.whitelist(allow_guest=True)
def send_ultramsg_message(msg_to, msg_body, quotedMsg):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/chat"
	headers = {"content-type": "application/x-www-form-urlencoded"}

	payload = {
		"to": msg_to,
		"body": msg_body,
		"token": ULTRAMSG_TOKEN,
		"msgId": quotedMsg,
		"referenceId": quotedMsg,
	}

	response = requests.request("POST", url, headers=headers, data=payload)
	return response.json()


def send_ultramsg_image(msg_to, msg_body, quotedMsg, image):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/image"
	headers = {"content-type": "application/x-www-form-urlencoded"}

	payload = {
		"to": msg_to,
		"caption": msg_body,
		"token": ULTRAMSG_TOKEN,
		"msgId": quotedMsg,
		"referenceId": quotedMsg,
		"image": image,
	}

	response = requests.request("POST", url, headers=headers, data=payload)
	return response.json()


def send_ultramsg_audio(msg_to, quotedMsg, audio):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/audio"
	headers = {"content-type": "application/x-www-form-urlencoded"}

	payload = {
		"to": msg_to,
		"token": ULTRAMSG_TOKEN,
		"msgId": quotedMsg,
		"referenceId": quotedMsg,
		"audio": audio,
	}

	response = requests.request("POST", url, headers=headers, data=payload)
	return response.json()


def send_ultramsg_document(msg_to, msg_body, quotedMsg, document, filename):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/document"
	headers = {"content-type": "application/x-www-form-urlencoded"}

	payload = {
		"to": msg_to,
		"caption": msg_body,
		"token": ULTRAMSG_TOKEN,
		"msgId": quotedMsg,
		"referenceId": quotedMsg,
		"filename": filename,
		"document": document,
	}

	response = requests.request("POST", url, headers=headers, data=payload)
	return response.json()


def save_message_data(message_to_save):
	# Check if contact_id already exists in Frappe
	existing_message = frappe.db.exists("WhatsApp Message", message_to_save.msg_id)
	# existing_message = frappe.get_value(
	#     "WhatsApp Message",
	#     {"message_id": message_to_save.msg_id},
	#     ["message_id", "name", "author", "message_from", "message_to"]  # Get the document name (primary key)
	# )

	if existing_message:
		# Update the existing document
		doc = frappe.get_doc("WhatsApp Message", existing_message)

		doc.ack_status = message_to_save.ack_status

		if message_to_save.media:
			doc.media = message_to_save.media

		if message_to_save.file_name:
			doc.file_name = message_to_save.file_name

		if message_to_save.quoted_message_id:
			doc.quoted_message = message_to_save.quoted_message_id

		doc.save(ignore_permissions=True)
		frappe.db.commit()

	else:
		# Insert a new document
		doc = frappe.get_doc(
			{
				"doctype": "WhatsApp Message",
				"message_id": message_to_save.msg_id,
				"message_from": message_to_save.msg_sender,
				"from_me": message_to_save.from_me,
				"ack_status": message_to_save.ack_status,
				"media": message_to_save.media,
				"timestamp": convert_to_local_time(message_to_save.timestamp),
				"is_forwarded": message_to_save.is_forwarded,
				"author": message_to_save.author,
				"message_to": message_to_save.msg_receiver,
				"type": message_to_save.type,
				"file_name": message_to_save.file_name,
				"quoted_message": message_to_save.quoted_message_id,
				"is_mentioned": message_to_save.is_mentioned,
				"message_body": message_to_save.message_body,
				"message_type": message_to_save.message_type,
			}
		)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()


def parse_message(text):
	# Split the message into two parts based on 'message_id='
	parts = text.rsplit(MESSAGE_ID_TAG, 1)

	if len(parts) == 2:
		body = parts[0].strip()  # All text before 'message_id='
		message_id = parts[1].strip()  # The value after '='
		return {"body": body, "message_id": message_id}
	else:
		# 'message_id=' not found
		return {"body": text.strip(), "message_id": None}


# if the message is from client or a group, send the message to managers
def send_reply_to_group(message_to_save: IncomingMessage):
	if not message_to_save.quoted_message:
		# If there is no quoted message, do nothing
		return message_to_save

	message_from_me = frappe.get_value(
		"WhatsApp Message",
		{"message_id": message_to_save.quoted_message_id},
		["message_id", "message_from", "quoted_message"],
		as_dict=True,
	)

	if not message_from_me:
		return

	original_message = frappe.get_value(
		"WhatsApp Message",
		{"message_id": message_from_me["quoted_message"]},
		["message_id", "message_from"],
		as_dict=True,
	)

	if not original_message:
		return

	# message_to_save.quoted_message = original_message["message_id"]
	send_ultramsg_message(
		msg_to=original_message["message_from"],
		msg_body=message_to_save.message_body,
		quotedMsg=original_message["message_id"],
	)

	return


def in_managers(msg_sender):
	whatsapp_managers = frappe.get_all(
		"Whatsapp Manager",
		fields=["name", "contact_person"],  # replace with fields you need
	)

	for manager in whatsapp_managers:
		if msg_sender == manager.contact_person:
			return True

	return False


def in_client_group(client_group):
	group_mappings = frappe.get_all(
		"Whatsapp Group Mapping", filters={"client_group": client_group}, fields=["name", "client_group"]
	)

	if group_mappings:
		return True

	return False


def in_member_of_client_group(msg_sender):
	existing_participant = frappe.get_all(
		"WhatsApp Group Participant",
		filters={"participant": msg_sender},
		fields=["id", "group", "participant"],
	)

	# Check if contact_id already exists in Frappe
	if not existing_participant:
		return False

	for gp in existing_participant:
		group_mappings = frappe.get_all(
			"Whatsapp Group Mapping", filters={"client_group": gp.group}, fields=["name", "client_group"]
		)

		if group_mappings:
			return True

	return False


def in_support_group(support_group):
	group_mappings = frappe.get_all(
		"Whatsapp Group Mapping", filters={"support_group": support_group}, fields=["name", "support_group"]
	)

	if group_mappings:
		return True

	return False


def on_receive_from_client_group(message_to_save: IncomingMessage):
	"""Set status when a new client message is received."""
	message_to_save.message_type = REPLY_FROM_SUPPORT

	# first we save messae as it is from client
	save_message_data(message_to_save=message_to_save)

	# first only print body and give 2 lines gap
	message_body_text = f"{message_to_save.message_body}\n\n\n"

	# if user wants to print group and author details, include these details
	if INCLUDE_SENDER_DETAILS:
		message_body_text += f"*Group:* {get_author_name(message_to_save.msg_sender)}\n"
		message_body_text += f"*From:* {get_author_name(message_to_save.author)}\n\n"

	# finally the message id to keep track of backward route
	message_body_text += f"{MESSAGE_ID_TAG}"
	message_body_text += f"\n{message_to_save.msg_id}"

	send_to_support_group(message_to_save=message_to_save, message_body=message_body_text)
	return


def on_receive_from_support_group(message_to_save: IncomingMessage):
	if not message_to_save.quoted_message_id:
		# if support team did not reply to original messae
		send_ultramsg_message(
			msg_to=message_to_save.msg_sender,
			msg_body="Please reply by selecting original client message",
			quotedMsg=None,
		)

	message_to_save.message_type = REPLY_FROM_SUPPORT
	# first we save messae as it is from client
	save_message_data(message_to_save=message_to_save)

	# first only print body and give 2 lines gap
	message_body_text = f"{message_to_save.message_body}\n\n"

	# if user wants to print group and author details, include these details
	if INCLUDE_SENDER_DETAILS:
		message_body_text += f"*Regards:*\n{get_author_name(message_to_save.author)}"

	send_to_client_group(message_to_save, message_body=message_body_text)
	return


def get_author_name(contact_id):
	existing_contact = frappe.db.get_value(
		"WhatsApp Contact", contact_id, ["contact_id", "contact_title", "contact_number"], as_dict=True
	)

	if not existing_contact:
		return None

	return (
		existing_contact["contact_title"]
		or existing_contact["contact_number"]
		or existing_contact["contact_id"]
	)


# if received for support group
def send_to_support_group(message_to_save: IncomingMessage, message_body):
	group_mappings = frappe.get_all(
		"Whatsapp Group Mapping",
		filters={"client_group": message_to_save.msg_sender},
		fields=["name", "support_group"],
	)

	if not group_mappings:
		return None

	for mapping in group_mappings:
		existing_contact = frappe.db.get_value("WhatsApp Contact", mapping.support_group, ["contact_id"])

		if not existing_contact:
			continue

		if message_to_save.type == "image":
			send_ultramsg_image(
				msg_to=existing_contact,
				msg_body=message_body,
				quotedMsg=message_to_save.quoted_message_id,
				image=message_to_save.media,
			)
		elif message_to_save.type == "ptt" or message_to_save.type == "audio":
			send_ultramsg_audio(
				msg_to=existing_contact,
				quotedMsg=message_to_save.quoted_message_id,
				audio=message_to_save.media,
			)
		elif message_to_save.type == "document":
			send_ultramsg_document(
				msg_to=existing_contact,
				msg_body=message_body,
				quotedMsg=message_to_save.quoted_message_id,
				document=message_to_save.media,
				filename=message_to_save.file_name,
			)
		else:
			send_ultramsg_message(
				msg_to=existing_contact, msg_body=message_body, quotedMsg=message_to_save.quoted_message_id
			)

	return


# if received for support group
def send_to_client_group(message_to_save: IncomingMessage, message_body):
	group_mappings = frappe.get_all(
		"Whatsapp Group Mapping",
		filters={"support_group": message_to_save.msg_sender},
		fields=["name", "client_group"],
	)

	if not group_mappings:
		frappe.log_error("No mapping defined in Whatsapp Group Mapping")
		return None

	# get previous message from quoted_message
	message_from_me = frappe.get_value(
		"WhatsApp Message",
		{"message_id": message_to_save.quoted_message_id},
		["message_id", "message_from", "quoted_message"],
		as_dict=True,
	)

	if not message_from_me:
		frappe.log_error("Quoted message not found.")
		return

	original_message = frappe.get_value(
		"WhatsApp Message",
		{"message_id": message_from_me["quoted_message"]},
		["message_id", "message_from"],
		as_dict=True,
	)

	if not original_message:
		frappe.log_error("Original client message not found")
		return

	for mapping in group_mappings:
		# Check if contact already exists
		existing_contact = frappe.get_value(
			"WhatsApp Contact", {"contact_id": mapping.client_group}, "contact_id"
		)

		if not existing_contact:
			frappe.log_error("Contact defined in mapping not found")
			continue

		if message_to_save.type == "image":
			send_ultramsg_image(
				msg_to=existing_contact,
				msg_body=message_body,
				quotedMsg=original_message["message_id"],
				image=message_to_save.media,
			)
		elif message_to_save.type == "ptt" or message_to_save.type == "audio":
			send_ultramsg_audio(
				msg_to=existing_contact, quotedMsg=original_message["message_id"], audio=message_to_save.media
			)
		elif message_to_save.type == "document":
			send_ultramsg_document(
				msg_to=existing_contact,
				msg_body=message_body,
				quotedMsg=original_message["message_id"],
				document=message_to_save.media,
				filename=message_to_save.file_name,
			)
		else:
			send_ultramsg_message(
				msg_to=existing_contact, msg_body=message_body, quotedMsg=original_message["message_id"]
			)

		# send_ultramsg_message(msg_to=existing_contact, msg_body=message_body, quotedMsg=original_message["message_id"])

	return


def on_forward_to_support_group(message_to_save: IncomingMessage):
	"""Set status when message is forwarded."""
	message_to_save.message_type = MESSAGE_TO_SUPPORT
	body_parts = parse_message(message_to_save.message_body)

	message_to_save.quoted_message_id = body_parts["message_id"]
	message_to_save.message_body = body_parts["body"]

	save_message_data(message_to_save=message_to_save)

	return


def on_forward_to_client_group(message_to_save: IncomingMessage):
	"""Set status when reply is sent back to client."""
	message_to_save.message_type = REPLY_TO_CLIENT
	save_message_data(message_to_save=message_to_save)
	return


def on_unidentified_message(message_to_save: IncomingMessage):
	"""Set status when an Unidentified message is received."""
	message_to_save.message_type = UNIDENTIFIED_MESSAGE
	save_message_data(message_to_save=message_to_save)


def get_contact_from_ultramsg(contact_id):
	# Amir Baloch Created To sync Contacts
	"""Fetch contacts from UltraMsg API and sync with Frappe."""
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts/contact"
	headers = {"content-type": "application/json"}
	params = {"token": ULTRAMSG_TOKEN, "chatId": contact_id}
	response = requests.request("GET", url, headers=headers, params=params)
	response.raise_for_status()  # Raise an error for failed requests
	return response.json()  # Extract contact list


@frappe.whitelist()
def sync_contacts():
	enqueue("whatsapp_management.whatsapp_management.apis.api.sync_contacts_enque")
	# enqueue(sync_contacts_enque)
	return "Contact sync has been queued."


def sync_contacts_enque():
	"""Fetch contacts from UltraMsg API and sync with Frappe."""
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts"
	headers = {"content-type": "application/json"}
	params = {"token": ULTRAMSG_TOKEN}

	try:
		response = requests.get(url, headers=headers, params=params)
		response.raise_for_status()  # Raise an error for failed requests

		contacts = response.json()  # Extract contact list

		frappe.log_error(f"About to sync contacts at [{datetime.datetime.now().isoformat()}]")

		for idx, contact in enumerate(contacts):
			create_contact(contact)

			# for now, i am disabling group participants, may be we need this later
			# if contact.get("isGroup"):
			# 	create_group_participant(contact)

			if idx % 50 == 0:
				frappe.db.commit()

		frappe.db.commit()  # Commit changes

		frappe.log_error(f"Contacts Synced Successfully! [{datetime.datetime.now().isoformat()}]")
		return "Contacts Synced Successfully!"

	except requests.exceptions.RequestException as e:
		frappe.log_error(f"WhatsApp Contact Sync Error: {str(e)}")
		return "Failed to sync contacts. Check error log."


def create_contact(contact):
	if not isinstance(contact, dict):
		frappe.throw(f"Something went wrong.\nInvalid contact format:\n{contact}")
		return  # This line won't be reached due to frappe.throw(), but it's good practice

	contact_id = contact.get("id")  # Ensure this field exists
	name = contact.get("name", "Unknown Contact")

	recipient_number = contact.get("number", "")
	num = "+" + recipient_number
	number = ""
	if is_valid_number(num):
		parsed_number = phonenumbers.parse(num, None)
		number = f"+{parsed_number.country_code}-{parsed_number.national_number}"

	pushname = contact.get("pushname", "")
	isMe = contact.get("isMe")
	isGroup = contact.get("isGroup")
	isBusiness = contact.get("isBusiness")
	isMyContact = contact.get("isMyContact")
	isBlocked = contact.get("isBlocked")
	isMuted = contact.get("isMuted")
	contactTitle = contact.get("name") or contact.get("pushname") or contact.get("number")

	# Check if contact already exists
	existing_contact = frappe.get_value("WhatsApp Contact", {"contact_id": contact_id}, "name")

	if not existing_contact:
		# profile = get_profile_photo(contact_id)
		# image = profile.get("success")
		doc = frappe.get_doc(
			{
				"doctype": "WhatsApp Contact",
				"contact_id": contact_id,
				"contact_name": name,
				"contact_number": number,
				"push_name": pushname,
				"is_me": isMe,
				"is_group": isGroup,
				"is_business": isBusiness,
				"is_my_contact": isMyContact,
				"is_blocked": isBlocked,
				"is_muted": isMuted,
				"contact_title": contactTitle,
				# "image": image,
			}
		)
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_doc("WhatsApp Contact", existing_contact)
		updated = False

		if doc.contact_name != name:
			doc.contact_name = name
			updated = True
		if doc.push_name != pushname:
			doc.push_name = pushname
			updated = True
		if doc.contact_title != contactTitle:
			doc.contact_title = contactTitle
			updated = True

		# Optional: update other fields if needed
		if updated:
			doc.save(ignore_permissions=True)


def create_group_participant(contact):
	group_id = contact.get("id")

	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/groups/group"
	headers = {"content-type": "application/json"}
	params = {"token": ULTRAMSG_TOKEN, "groupId": group_id}

	try:
		response = requests.get(url, headers=headers, params=params)
		response.raise_for_status()  # Raise an error for failed requests

		participants = (
			response.json().get("groupMetadata", {}).get("participants", [])
		)  # Extract contact list

		for participant in participants:
			# Check if contact already exists
			existing_participant = frappe.get_value(
				"WhatsApp Group Participant",
				{"group": group_id, "participant": participant.get("id")},
				"name",
			)

			# Check if contact_id already exists in Frappe
			if not existing_participant:
				doc = frappe.get_doc(
					{
						"doctype": "WhatsApp Group Participant",
						"group": group_id,
						"participant": participant.get("id"),
						"is_admin": participant.get("isAdmin"),
						"is_super_admin": participant.get("isSuperAdmin"),
					}
				)
				doc.insert(ignore_permissions=True)

		# frappe.db.commit()  # Commit changes
		return "Contacts Synced Successfully!"

	except requests.exceptions.RequestException as e:
		frappe.log_error(f"WhatsApp Group Sync Error: {str(e)}")
		return "Failed to sync contacts. Check error log."


@frappe.whitelist()
def get_user_info():
	user = frappe.db.exists("User", frappe.session.user)
	if not user:
		raise Exception("You are not allowed to login")
	data = {}
	data["user"] = frappe.get_doc("User", user)
	return data


# Amir baloch removed whitelist temporary
# @frappe.whitelist(allow_guest=True)
def sent_message(data):
	data = frappe.parse_json(data)
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/chat"
	headers = {"content-type": "application/x-www-form-urlencoded"}
	to = data.get("to")
	body = data.get("body")
	payload = {"to": to, "body": body, "token": ULTRAMSG_TOKEN}
	response = requests.request("POST", url, headers=headers, data=payload)
	return response.json()


@frappe.whitelist()
def sync_conversations():
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats"
	querystring = {"token": ULTRAMSG_TOKEN}
	headers = {"content-type": "application/x-www-form-urlencoded"}

	response = requests.request("GET", url, headers=headers, params=querystring)

	for record in response.json():
		idVar = record.get("id")

		profile = get_profile_photo(idVar)
		pro_photo = profile.get("success")

		if record.get("isGroup"):
			group_id = record.get("id")
			group_name = record.get("name")
			if group_name:
				create_group(group_id, group_name, pro_photo)
		elif not record.get("isGroup"):
			recipient_id = record.get("id")
			recipient_name = record.get("name")
			if recipient_name:
				recipient_number = recipient_id.split("@")[0]
				num = "+" + recipient_number
				if is_valid_number(num):
					parsed_number = phonenumbers.parse(num, None)
					formatted_number = f"+{parsed_number.country_code}-{parsed_number.national_number}"
					create_recipient(recipient_id, recipient_name, formatted_number, pro_photo)
					create_conversation(recipient_id, recipient_name)


@frappe.whitelist()
def sync_conver(conversation_id, name):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats/messages"
	headers = {"content-type": "application/x-www-form-urlencoded"}
	querystring = {"token": ULTRAMSG_TOKEN, "chatId": conversation_id}
	response = requests.request("GET", url, headers=headers, params=querystring)
	for r in response.json():
		body = r.get("body")
		if body:
			ts = r.get("timestamp")
			readable_time = convert_to_local_time(ts)
			sender = "User" if r.get("fromMe") else "Recipient"
			rec = None
			if sender == "Recipient":
				rec = frappe.db.get_value("WhatsApp Recipient", {"id": r.get("from")}, "id") or None
			create_message(conversation=name, body=body, readable_time=readable_time, sender=sender, rec=rec)
	return response.json()


@frappe.whitelist()
def sync_grp(group_id, name):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats/messages"
	headers = {"content-type": "application/x-www-form-urlencoded"}
	querystring = {"token": ULTRAMSG_TOKEN, "chatId": group_id}
	response = requests.request("GET", url, headers=headers, params=querystring)
	for r in response.json():
		body = r.get("body")
		if body:
			ts = r.get("timestamp")
			readable_time = convert_to_local_time(ts)
			sender = "User" if r.get("fromMe") else "Recipient"
			recipient_id = r.get("author")
			rec = None
			if sender == "Recipient":
				rec = frappe.db.get_value("WhatsApp Recipient", {"id": recipient_id}, "id") or None
				if not rec:
					recipient_number = recipient_id.split("@")[0]
					num = "+" + recipient_number
					if is_valid_number(num):
						parsed_number = phonenumbers.parse(num, None)
						formatted_number = f"+{parsed_number.country_code}-{parsed_number.national_number}"
						no = f"+{parsed_number.country_code}{parsed_number.national_number}"
						create_recipient(recipient_id, no, formatted_number)
						rec = frappe.db.get_value("WhatsApp Recipient", {"id": recipient_id}, "id")
			create_message(
				whatsapp_group=name,
				body=body,
				readable_time=readable_time,
				sender=sender,
				rec=rec,
				author=recipient_id,
			)
	return response.json()


@frappe.whitelist()
def delete_conversations():
	frappe.db.sql("DELETE FROM `tabWhatsApp Conversation`")
	frappe.db.sql("DELETE FROM `tabWhatsApp Group`")
	frappe.db.commit()


def get_profile_photo(id):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts/image"
	headers = {"content-type": "application/x-www-form-urlencoded"}
	querystring = {"token": ULTRAMSG_TOKEN, "chatId": id}
	response = requests.request("GET", url, headers=headers, params=querystring)

	return response.json()


def convert_to_local_time(timestamp):
	utc_time = datetime.datetime.utcfromtimestamp(timestamp)
	utc_time = pytz.utc.localize(utc_time)
	local_tz = pytz.timezone(TIMEZONE)
	local_time = utc_time.astimezone(local_tz)
	return local_time.strftime("%Y-%m-%d %H:%M:%S")


def is_valid_number(number):
	try:
		parsed_number = phonenumbers.parse(number, None)
		return phonenumbers.is_valid_number(parsed_number)
	except phonenumbers.NumberParseException:
		return False


def create_group(group_id, group_name, pro_photo=None):
	existing_group = frappe.db.exists("WhatsApp Group", {"id": group_id})
	if existing_group:
		frappe.db.set_value("WhatsApp Group", existing_group, "id_name", group_name, update_modified=False)
		frappe.db.set_value(
			"WhatsApp Group", existing_group, "profile_photo", pro_photo, update_modified=False
		)
	else:
		doc = frappe.get_doc(
			{"doctype": "WhatsApp Group", "id_name": group_name, "id": group_id, "profile_photo": pro_photo}
		)
		doc.flags.ignore_permissions = True
		doc.insert()


def create_conversation(conversation_id, recipient_name):
	existing_conversation = frappe.db.exists("WhatsApp Conversation", {"conversation_id": conversation_id})
	if not existing_conversation:
		recipient = frappe.db.get_value("WhatsApp Recipient", {"id": conversation_id}, "id")
		doc = frappe.get_doc(
			{
				"doctype": "WhatsApp Conversation",
				"recipient": recipient or recipient_name,
				"conversation_id": conversation_id,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()


def create_recipient(recipient_id, recipient_name, formatted_number, pro_photo=None):
	existing_recipient = frappe.db.exists("WhatsApp Recipient", {"id": recipient_id})
	if existing_recipient:
		frappe.db.set_value(
			"WhatsApp Recipient", existing_recipient, "id_name", recipient_name, update_modified=False
		)
		frappe.db.set_value(
			"WhatsApp Recipient", existing_recipient, "profile_photo", pro_photo, update_modified=False
		)
		conversation = frappe.db.get_value("WhatsApp Conversation", {"recipient": recipient_id}, "name")
		if conversation:
			frappe.db.set_value(
				"WhatsApp Conversation", conversation, "recipient", recipient_id, update_modified=False
			)
	else:
		recipient_doc = frappe.get_doc(
			{
				"doctype": "WhatsApp Recipient",
				"id_name": recipient_name,
				"id": recipient_id,
				"recipient_number": formatted_number,
				"profile_photo": pro_photo,
			}
		)
		recipient_doc.flags.ignore_permissions = True
		recipient_doc.insert()


def create_message(
	msg_id=None,
	conversation=None,
	whatsapp_group=None,
	body=None,
	readable_time=None,
	sender=None,
	rec=None,
	media_url=None,
	author=None,
):
	existing_recipient = frappe.db.exists("WhatsApp Message", {"message_id": msg_id})

	if existing_recipient:
		return

	doc = frappe.get_doc(
		{
			"doctype": "WhatsApp Message",
			"conversation": conversation,
			"whatsapp_group": whatsapp_group,
			"message_content": body,
			"timestamp": readable_time,
			"sender": sender,
			"recipient": rec,
			"media_url": media_url,
			"message_author": author,
			"message_id": msg_id,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def get_conver_name(id):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts/contact"
	querystring = {"token": ULTRAMSG_TOKEN, "chatId": id}

	headers = {"content-type": "application/x-www-form-urlencoded"}
	response = requests.request("GET", url, headers=headers, params=querystring)
	return response.json().get("name")


def get_grp_name(id):
	url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/groups/group"
	querystring = {"token": ULTRAMSG_TOKEN, "groupId": id}

	headers = {"content-type": "application/x-www-form-urlencoded"}
	response = requests.request("GET", url, headers=headers, params=querystring)
	return response.json().get("name")


def handle_group_message(msg_id, group_id, message, sender, timestamp, media, author):
	readable_time = convert_to_local_time(timestamp)
	group_record_name = frappe.db.get_value("WhatsApp Group", {"id": group_id}, "name")
	if author:
		author_name = frappe.db.get_value("WhatsApp Recipient", {"id": author}, "id") or None
	if not author_name:
		number = author.split("@")[0]
		author_name = "+" + number
	create_message(
		msg_id=msg_id,
		whatsapp_group=group_record_name,
		body=message,
		readable_time=readable_time,
		sender=sender,
		media_url=media,
		author=author_name,
	)


def handle_private_message(msg_id, msg_sender, message, sender, timestamp, media):
	readable_time = convert_to_local_time(timestamp)
	conversation_record_name = frappe.db.get_value(
		"WhatsApp Conversation", {"conversation_id": msg_sender}, "name"
	)
	create_message(
		msg_id=msg_id,
		conversation=conversation_record_name,
		body=message,
		readable_time=readable_time,
		sender=sender,
		media_url=media,
	)


def on_receive_message(message_to_save: IncomingMessage):
	"""Set status when a new client message is received."""
	message_to_save.message_type = MESSAGE_FROM_CLIENT

	# first we save messae as it is from client
	save_message_data(message_to_save=message_to_save)

	message_body = f"{message_to_save.message_body}\n\n\nmessage_id={message_to_save.msg_id}"

	send_to_managers(message_body=message_body, quoted_message=message_to_save.quoted_message)
	return


def on_forward_to_managers(message_to_save: IncomingMessage):
	"""Set status when message is forwarded."""
	message_to_save.message_type = MESSAGE_TO_SUPPORT
	body_parts = parse_message(message_to_save.message_body)

	message_to_save.quoted_message_id = body_parts["message_id"]
	message_to_save.message_body = body_parts["body"]

	save_message_data(message_to_save=message_to_save)

	return


def on_REPLY_FROM_SUPPORT(message_to_save: IncomingMessage):
	"""Set status when manager replies."""
	message_to_save.message_type = REPLY_FROM_SUPPORT

	save_message_data(message_to_save=message_to_save)

	send_reply_to_group(message_to_save=message_to_save)
	return


def on_reply_to_client(message_to_save: IncomingMessage):
	"""Set status when reply is sent back to client."""
	message_to_save.message_type = REPLY_TO_CLIENT
	save_message_data(message_to_save=message_to_save)
	return


# if the message is from client or a group, send the message to managers
def send_to_managers(message_body, quoted_message):
	whatsapp_managers = frappe.get_all(
		"Whatsapp Manager",
		fields=["name", "contact_person"],  # replace with fields you need
	)

	# altered_body = f"Sender: {msg_sender}\nOriginal Message:{original_message_id}\n\nMessage:{message_body}"

	for manager in whatsapp_managers:
		# Check if contact already exists
		existing_contact = frappe.get_value(
			"WhatsApp Contact", {"contact_id": manager.contact_person}, "contact_number"
		)

		if not existing_contact:
			continue

		send_ultramsg_message(msg_to=existing_contact, msg_body=message_body, quotedMsg=quoted_message)

	return
