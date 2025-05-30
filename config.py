import os

# Main config.py
language = os.getenv('Lang')

SETTINGS = {
    "command_role": 1336046637901938740,
    "hasntRole_embed_color": 0xff1100,
    "GUILD": os.getenv('Guild'),
    "TOKEN": os.getenv("BOT_TOKEN")
}
DATABASE = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}
LANG = {
    "name": "Discord SukaBot 3000",
    "author": "Author",
    "Discord": "Discord",
    "Discord_link": "[Link](https://discord.gg/XTe6D8czUs)",
    "Main_Language": "Main Language",
    "role": {
        "hasntRole_title": "ERROR",
        "hasntRole_description": ":flag_ru: **RU**\nУ вас нет доступа!\n\n:flag_us: **EN**\nYou don't have access!"
    }
}
