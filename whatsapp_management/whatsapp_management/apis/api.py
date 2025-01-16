import requests
import frappe
import phonenumbers
import datetime
import pytz

wa_settings = frappe.get_doc("WhatsApp Settings")
ULTRAMSG_API = wa_settings.api_url
ULTRAMSG_INSTANCE = wa_settings.instance_id
ULTRAMSG_TOKEN = wa_settings.token
TIMEZONE = frappe.db.get_single_value('System Settings', 'time_zone')





@frappe.whitelist()
def get_user_info():
    user = frappe.db.exists("User", frappe.session.user)
    if not user:
        raise Exception("You are not allowed to login")
    data = {}
    data["user"] = frappe.get_doc("User", user)
    return data



@frappe.whitelist(allow_guest=True)
def sent_message(data):
    # print("Data", data)
    data = frappe.parse_json(data)
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/chat"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    to = data.get("to")
    body = data.get("body")
    payload = {
        "to": to,
        "body": body,
        "token": ULTRAMSG_TOKEN  
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    return response.json()






@frappe.whitelist()
def sync_conversations():
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats"
    querystring = {
        "token": ULTRAMSG_TOKEN
    }
    
    
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    response = requests.request("GET", url, headers=headers, params=querystring)
    # print(response.text)
    for record in response.json():
        if record.get("isGroup"):
            group_id = record.get("id")
            group_name = record.get("name")
            if group_name:
                create_group(group_id, group_name)
        elif not record.get("isGroup"):
            recipient_id = record.get("id")
            recipient_name = record.get("name")
            if recipient_name:
                recipient_number = recipient_id.split("@")[0]
                num = '+' + recipient_number
                if is_valid_number(num):
                    parsed_number = phonenumbers.parse(num, None)
                    formatted_number = f'+{parsed_number.country_code}-{parsed_number.national_number}'
                    create_recipient(recipient_id, recipient_name, formatted_number)
                    create_conversation(recipient_id, recipient_name)
    return response.json()





@frappe.whitelist()
def sync_conver(conversation_id, name):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats/messages"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    
    querystring = {
        "token": ULTRAMSG_TOKEN,
        "chatId": conversation_id
    }
    response = requests.request("GET", url, headers=headers, params=querystring)
    # print(response.text)
    for r in response.json():
        body = r.get("body")
        if body:
            ts = r.get("timestamp")
            readable_time = convert_to_local_time(ts)
            sender = "User" if r.get("fromMe") else "Recipient"
            rec = None
            if sender == "Recipient":
                rec = frappe.db.get_value('WhatsApp Recipient', {'recipient_id': r.get("from")}, 'recipient_name') or None
            create_message(conversation=name, body=body, readable_time=readable_time, sender=sender, rec=rec)
    return response.json()






@frappe.whitelist()
def sync_grp(group_id, name):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/chats/messages"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    
    querystring = {
        "token": ULTRAMSG_TOKEN,
        "chatId": group_id
    }
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
                rec = frappe.db.get_value('WhatsApp Recipient', {'recipient_id': recipient_id}, 'recipient_name') or None
                if not rec:
                    recipient_number = recipient_id.split("@")[0]
                    num = '+' + recipient_number
                    if is_valid_number(num):
                        parsed_number = phonenumbers.parse(num, None)
                        formatted_number = f'+{parsed_number.country_code}-{parsed_number.national_number}'
                        no = f'+{parsed_number.country_code}{parsed_number.national_number}'
                        create_recipient(recipient_id, no, formatted_number)
                        rec = frappe.db.get_value('WhatsApp Recipient', {'recipient_id': recipient_id}, 'recipient_name')

            create_message(whatsapp_group=name, body=body, readable_time=readable_time, sender=sender, rec=rec)
    return response.json()







@frappe.whitelist()
def delete_conversations():
    frappe.db.sql("DELETE FROM `tabWhatsApp Conversation`")
    frappe.db.sql("DELETE FROM `tabWhatsApp Group`")
    frappe.db.commit()






@frappe.whitelist(allow_guest=True)
def handle_incoming_webhook(data):
    # print("Data", data)
    message_data = frappe.parse_json(data)
    msg_sender = message_data.get("from")
    message = message_data.get("body")
    msg_receiver = message_data.get("to")
    author = message_data.get("author")
    timestamp = message_data.get("time")
    fromme = message_data.get("fromMe")
    media = message_data.get("media")
    if not fromme:
        sender = 'Recipient'
        number = msg_sender.split("@")[0]
        num = '+' + number
        if is_valid_number(num):
            parsed_number = phonenumbers.parse(num, None)
            formatted_number = f'+{parsed_number.country_code}-{parsed_number.national_number}'
            conver_name = get_conver_name(msg_sender)
            create_recipient(msg_sender, conver_name or num, formatted_number)
            create_conversation(msg_sender, conver_name or num)
            handle_private_message(msg_sender, message, sender, timestamp, media)
        else:
            grp_name = get_grp_name(msg_sender)
            create_group(msg_sender, grp_name)
            handle_group_message(msg_sender, message, sender, timestamp, media, author)
    else:
        sender = 'User'
        number = msg_receiver.split("@")[0]
        num = '+' + number
        if is_valid_number(num):
            parsed_number = phonenumbers.parse(num, None)
            formatted_number = f'+{parsed_number.country_code}-{parsed_number.national_number}'
            conver_name = get_conver_name(msg_receiver)
            create_recipient(msg_receiver, conver_name or num, formatted_number)
            create_conversation(msg_receiver, conver_name or num)
            handle_private_message(msg_receiver, message, sender, timestamp, media)
        else:
            grp_name = get_grp_name(msg_receiver)
            create_group(msg_receiver, grp_name)
            handle_group_message(msg_receiver, message, sender, timestamp, media, author)

    return {"status": "success"}







def convert_to_local_time(timestamp):    
    utc_time = datetime.datetime.utcfromtimestamp(timestamp)
    utc_time = pytz.utc.localize(utc_time)
    local_tz = pytz.timezone(TIMEZONE)
    local_time = utc_time.astimezone(local_tz)
    return local_time.strftime('%Y-%m-%d %H:%M:%S')

def is_valid_number(number):
    try:
        parsed_number = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed_number)
    except phonenumbers.NumberParseException:
        return False

def create_group(group_id, group_name):
    existing_group = frappe.db.exists('WhatsApp Group', {'group_id': group_id})
    if existing_group:
        frappe.db.set_value('WhatsApp Group', existing_group, 'group_name', group_name, update_modified=False)
    else:
        doc = frappe.get_doc({
            'doctype': 'WhatsApp Group',
            'group_name': group_name,
            'group_id': group_id,
        })
        doc.flags.ignore_permissions = True
        doc.insert()

def create_conversation(conversation_id, recipient_name):
    existing_conversation = frappe.db.exists('WhatsApp Conversation', {'conversation_id': conversation_id})
    if not existing_conversation:
        recipient = frappe.db.get_value('WhatsApp Recipient', {'recipient_id': conversation_id}, 'name')
        doc = frappe.get_doc({
            'doctype': 'WhatsApp Conversation',
            'recipient': recipient or recipient_name,
            'conversation_id': conversation_id,
        })
        doc.flags.ignore_permissions = True
        doc.insert()

def create_recipient(recipient_id, recipient_name, formatted_number):
    existing_recipient = frappe.db.exists('WhatsApp Recipient', {'recipient_id': recipient_id})
    if existing_recipient:
        frappe.db.set_value('WhatsApp Recipient', existing_recipient, 'recipient_name', recipient_name, update_modified=False)
        conversation = frappe.db.get_value('WhatsApp Conversation', {'recipient': recipient_name}, 'name')
        if conversation:
            frappe.db.set_value('WhatsApp Conversation', conversation, 'recipient', recipient_name, update_modified=False)
    else:
        recipient_doc = frappe.get_doc({
            'doctype': 'WhatsApp Recipient',
            'recipient_name': recipient_name,
            'recipient_id': recipient_id,
            'recipient_number': formatted_number
        })
        recipient_doc.flags.ignore_permissions = True
        recipient_doc.insert()

def create_message(conversation = None, whatsapp_group = None, body = None, readable_time = None, sender = None, rec = None, media_url = None, author = None):
    doc = frappe.get_doc({
                'doctype': 'WhatsApp Message',
                'conversation': conversation,
                'whatsapp_group': whatsapp_group,
                'message_content': body,
                'timestamp': readable_time,
                'sender': sender,
                'recipient': rec,
                'media_url': media_url,
                'message_author': author
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc

def get_conver_name(id):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts/contact"
    querystring = {
        "token": ULTRAMSG_TOKEN,
        "chatId": id
    }
    
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    response = requests.request("GET", url, headers=headers, params=querystring)
    return response.json().get("name")

def get_grp_name(id):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/groups/group"
    querystring = {
        "token": ULTRAMSG_TOKEN,
        "groupId": id
    }
    
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    response = requests.request("GET", url, headers=headers, params=querystring)
    return response.json().get("name")

def handle_group_message(group_id, message, sender, timestamp, media , author):
    readable_time = convert_to_local_time(timestamp)
    group_record_name = frappe.db.get_value('WhatsApp Group', {'group_id': group_id}, 'name')
    if author:
        author_name = frappe.db.get_value('WhatsApp Recipient', {'recipient_id': author}, 'recipient_name') or None
    if not author_name:
        number = author.split("@")[0]
        author_name = '+' + number
    create_message(whatsapp_group=group_record_name, body=message, readable_time=readable_time, sender=sender, media_url=media, author=author_name)

def handle_private_message(msg_sender, message, sender, timestamp, media):
    readable_time = convert_to_local_time(timestamp)
    conversation_record_name = frappe.db.get_value('WhatsApp Conversation', {'conversation_id': msg_sender}, 'name')
    create_message(conversation=conversation_record_name, body=message, readable_time=readable_time, sender=sender, media_url=media)
