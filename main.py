import discord
from discord.ext import bridge
import os
import config
from Modules.Tools.main import *
import aiohttp
from io import BytesIO
import config
import logging
from dotenv import load_dotenv

load_dotenv()
bot = bridge.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    """Событие запуска бота."""
    bot.http_session = aiohttp.ClientSession()
    print(f"Бот {bot.user} запущен!")
    logging.debug(f"Bot {bot.user} is running!")
    
    bot.auto_sync_commands=True
    await load_cogs()
    try:
        print(f"Синхронизировано команды: {bot.application_commands}")
    except Exception as e:
        print(f"Ошибка синхронизации команд: {e}")
        logging.critical(f"Ошибка синхронизации: {e}", exc_info=True)
        raise


async def load_cogs():
    """Функция загрузки всех модулей (cogs)."""
    print("Загружаем модули...")
    logging.debug("Loading modules...")

    loaded_cogs = []
    failed_cogs = []

    for folder in os.listdir("./Modules"):
        if folder.startswith('__') or not os.path.isdir(f"./Modules/{folder}"):
            continue
        cog_path = f"Modules.{folder}.main"
        if os.path.exists(f"./Modules/{folder}/main.py"):
            try:
                bot.load_extension(cog_path)
                loaded_cogs.append(folder)
            except Exception as e:
                failed_cogs.append((folder, str(e)))

    print(f"Загруженные модули: {', '.join(loaded_cogs) if loaded_cogs else 'Нет'}")
    logging.info(f"Загруженные модули: {', '.join(loaded_cogs) if loaded_cogs else 'Нет'}")

    if failed_cogs:
        print("Не удалось загрузить следующие модули:")
        logging.critical("Не удалось загрузить следующие модули:")
        for cog, error in failed_cogs:
            print(f"- {cog}: {error}")
            logging.critical(f"- {cog}: {error}")


async def unload_cogs():
    """Функция выгрузки всех модулей (cogs)."""
    print("Выгружаем модули...")
    logging.debug("Выгружаем модули...")

    unloaded_cogs = []
    failed_cogs = []

    for folder in os.listdir("./Modules"):
        cog_path = f"Modules.{folder}.main"
        if os.path.exists(f"./Modules/{folder}/main.py"):
            try:
                await bot.unload_extension(cog_path)
                unloaded_cogs.append(folder)
            except Exception as e:
                failed_cogs.append((folder, str(e)))

    print(f"Выгруженные модули: {', '.join(unloaded_cogs) if unloaded_cogs else 'Нет'}")
    logging.info(f"Выгруженные модули: {', '.join(unloaded_cogs) if unloaded_cogs else 'Нет'}")
    if failed_cogs:
        print("Модули с ошибкой:")
        logging.critical("Модули с ошибкой:")
        for cog, error in failed_cogs:
            print(f"- {cog}: {error}")
            logging.critical(f"- {cog}: {error}")


@bot.bridge_command(name="reload", description="Перезагружает модули")
@commands.has_role(config.SETTINGS["command_role"])
async def reload(ctx: discord.ApplicationContext):
    await ctx.defer()
    await unload_cogs()
    await load_cogs()
    try:
        await bot.sync_commands()
        await ctx.send("✅ Модули и команды перезагружены!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")


@bot.bridge_command(aliases=['dev'], description="Dev Info")
async def developer(ctx):
    await Tools.respond(ctx, embed=discord.Embed(title=config.LANG["name"])
    .add_field(name=config.LANG["author"], value="<@1061998983158964285>")
    .add_field(name=config.LANG["Discord"], value=config.LANG["Discord_link"])
    .add_field(name=config.LANG["Main_Language"], value="Eng")
    .set_thumbnail(url="https://images.wallpaperscraft.ru/image/single/mem_dovolnyj_litso_64470_1600x1200.jpg"))


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Обработчик ошибок команд."""
    if isinstance(error, commands.MissingRole):
        await Tools.respond(ctx, embed=discord.Embed(title="Error").add_field(name="У вас нет роли, необходимой для выполнения этой команды.", value=" "))
    elif isinstance(error, commands.MissingAnyRole):
        await Tools.respond(ctx, embed=discord.Embed(title="Error").add_field(name="Вам не хватает одной из необходимых ролей для выполнения этой команды.", value=" "))
    elif isinstance(error, commands.CommandNotFound):
        await Tools.respond(ctx, embed=discord.Embed(title="Error").add_field(name="Команда не найдена.", value=" "))
    elif isinstance(error, commands.CommandOnCooldown):
        await Tools.respond(ctx, embed=discord.Embed(title="Error").add_field(name=f"Команда на перезарядке. Подождите {round(error.retry_after, 2)} секунд.", value=" "))
    else:
        await Tools.respond(ctx, embed=discord.Embed(title="Error").add_field(name="Хз чё за ошибка", value=error))
        print(error)
        logging.error(error)


if __name__ == "__main__":
    try:
        logging.basicConfig(level=logging.DEBUG, filename="logs.xml", filemode="w")
        bot.run(str(config.SETTINGS["TOKEN"]))
    except Exception as e:
        print(f"Не удалось запустить бота: {e}")
        logging.critical(f"Не удалось запустить бота: {e}")