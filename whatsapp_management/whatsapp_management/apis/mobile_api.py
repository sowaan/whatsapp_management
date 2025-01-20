import frappe
import requests

wa_settings = frappe.get_doc("WhatsApp Settings")
ULTRAMSG_API = wa_settings.api_url
ULTRAMSG_INSTANCE = wa_settings.instance_id
ULTRAMSG_TOKEN = wa_settings.token
RECIPIENT = frappe.db.get_list('WhatsApp Recipient', fields=['name', 'id', 'id_name', 'recipient_number', 'profile_photo'])
GROUP = frappe.db.get_list('WhatsApp Group', fields=['name', 'id', 'id_name', 'profile_photo'])
MESSAGE = frappe.db.get_list('WhatsApp Message', fields=['name', 'message_id', 'message_content', 'timestamp', 'sender', 'recipient', 'whatsapp_group'])

@frappe.whitelist()
def sync_conversation_mobile():
    data = []
    for row in GROUP:
        grp_name = row.get("name")
        last_message = get_last_doc('WhatsApp Message', {'whatsapp_group': grp_name}, 'message_content')
        row["last_message"] = last_message
        row["isGroup"] = True
        row.pop("name", None)
        data.append(row)

    for row in RECIPIENT:
        rec_name = row.get("name")
        last_message = get_last_doc('WhatsApp Message', {'conversation': rec_name}, 'message_content')
        row["last_message"] = last_message
        row["isGroup"] = False
        row.pop("name", None)
        data.append(row)
        
    return data

def get_last_doc(doctype, filters, fieldname):
    return frappe.db.get_value(doctype, filters, fieldname, order_by='timestamp desc')

def get_profile_photo(id):
    url = f"{ULTRAMSG_API}/{ULTRAMSG_INSTANCE}/contacts/image"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    querystring = {
    "token": ULTRAMSG_TOKEN,
    "chatId": id
    }
    response = requests.request("GET", url, headers=headers, params=querystring)
    return response.json()
