import requests
import frappe

wa_settings = frappe.get_doc("WhatsApp Settings")
ULTRAMSG_API = wa_settings.api_url
ULTRAMSG_INSTANCE = wa_settings.instance_id
ULTRAMSG_TOKEN = wa_settings.token

def send_message(to, message):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/messages/chat"
    payload = {
        "token": ULTRAMSG_TOKEN,
        "to": to,
        "body": message,
    }
    response = requests.post(url, data=payload)
    return response.json()

def handle_group_message():
    pass

def handle_private_message():
    pass

@frappe.whitelist()
def sync_groups():
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/groups"
    querystring = {
        "token": ULTRAMSG_TOKEN
    }
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    response = requests.request("GET", url, headers=headers, params=querystring)
    for record in response.json():
        # print(record)
        if record.get("name") is not None and record.get("name") != '':
            doc = frappe.get_doc({
                'doctype': 'WhatsApp Group',
                'group_name': record.get("name"),
                'group_id': record.get("id"),
            })
            doc.insert()
        
    
@frappe.whitelist()
def sync_chats(to, message):
    pass

@frappe.whitelist(allow_guest=True)
def handle_incoming_webhook(payload):
    data = frappe.parse_json(payload)
    sender = data.get("from")
    message = data.get("body")
    is_group_message = data.get("isGroup")
    group_id = data.get("groupId") if is_group_message else None

    if is_group_message:
        handle_group_message(group_id, sender, message)
    else:
        handle_private_message(sender, message)

    return {"status": "success"}



