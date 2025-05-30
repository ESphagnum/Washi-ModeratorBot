import discord
from discord.ext import bridge, commands
import requests, json

class Tools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @staticmethod
    async def get_color(color_name: str) -> int:
        colors = {
            "green": 0x00FF00,
            "red": 0xFF0000,
            "blue": 0x0000FF,
            "default": 0x000000
        }
        return colors.get(color_name.lower(), colors["default"])

    @staticmethod
    async def respond(ctx, message: str=None, color=0x000000, embed: discord.Embed=None, view: discord.ui.View=None):
        if embed is not None and message is not None:
            raise AttributeError("Message is not None when embed is also not None")
        if embed is None:
            embed = discord.Embed(title=message, color=color)
        try:
            return await ctx.reply(embed=embed, mention_author=False, view=view)
        except:
            return await ctx.respond(embed=embed, view=view)

    @bridge.bridge_command()
    async def webhook(self, ctx: bridge.BridgeContext, url: str = None):
        """Отправляет вебхук с прикреплённым JSON-файлом"""
        if not url:
            embed = discord.Embed(
                title="Webhook Help",
                description="Использование:\n"
                           "`/webhook <url>` с прикреплённым JSON-файлом\n\n"
                           "[Гайд по вебхукам](https://birdie0.github.io/discord-webhooks-guide/)",
                color=await self.get_color("blue")
            )
            return await ctx.respond(embed=embed)
        
        if not ctx.message.attachments:
            return await ctx.respond("Прикрепите JSON-файл!", ephemeral=True)
        
        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.json'):
            return await ctx.respond("Файл должен быть в формате JSON!", ephemeral=True)
        
        try:
            file_content = await attachment.read()
            data = json.loads(file_content.decode('utf-8'))
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers)
            response.raise_for_status()
            
            await ctx.respond("Вебхук успешно отправлен!", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"Ошибка: {str(e)}", ephemeral=True)

    @bridge.bridge_command()
    async def color(self, ctx: bridge.BridgeContext, color_name: str):
        """Покажет HEX-код указанного цвета"""
        hex_code = await self.get_color(color_name)
        embed = discord.Embed(
            title=f"Цвет {color_name}",
            description=f"HEX: {hex(hex_code)}",
            color=hex_code
        )
        await ctx.respond(embed=embed)

def setup(bot):
    bot.add_cog(Tools(bot))