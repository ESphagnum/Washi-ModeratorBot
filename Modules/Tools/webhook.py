import requests, json

with open('webhook.json') as json_file:
    data = json.load(json_file)

url = 'https://discord.com/api/webhooks/1327708083836686456/zv2mXeZ76aVruKIgSYKOh7x6_6IgBKYSwkfWKXwFKLe_bQw57JoSzzKaUbbR6ES7UQap'
headers={"Content-Type": "application/json"}

requests.post(url, data=json.dumps(data), headers=headers)