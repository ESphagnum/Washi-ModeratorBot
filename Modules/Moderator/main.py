import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import mysql.connector
import re
import os
from config import DATABASE
from typing import Optional, Union

class Moderator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = self.setup_db()
        self.initialize_db()
        self.check_temp_punishments.start()
        self.voice_cache = {}

    def setup_db(self):
        # Настройки подключения к MySQL
        conn = mysql.connector.connect(
            host=DATABASE["host"],
            user=DATABASE["user"],
            password=DATABASE["password"],
            database=DATABASE["name"]
        )
        return conn
    
    def initialize_db(self):
        cursor = self.db.cursor(dictionary=True)
        
        # Улучшенная структура базы данных для MySQL
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(32) NOT NULL,
            discriminator VARCHAR(4),
            avatar_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS punishment_types (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(32) UNIQUE NOT NULL,
            is_temporary BOOLEAN DEFAULT FALSE
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS punishments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            moderator_id BIGINT NOT NULL,
            punishment_type_id INT NOT NULL,
            reason TEXT,
            duration_seconds INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NULL,
            revoked BOOLEAN DEFAULT FALSE,
            revoked_at TIMESTAMP NULL,
            revoked_by BIGINT,
            revoked_reason TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(punishment_type_id) REFERENCES punishment_types(id),
            FOREIGN KEY(moderator_id) REFERENCES users(user_id),
            FOREIGN KEY(revoked_by) REFERENCES users(user_id)
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS voice_activity (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            channel_name VARCHAR(100),
            join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            leave_time TIMESTAMP NULL,
            duration_seconds INT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            action_type VARCHAR(50) NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
        ''')
        
        # Создаем индексы для ускорения запросов
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_punishments_user ON punishments(user_id)
        ''')
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_punishments_expires ON punishments(expires_at)
        ''')
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_voice_activity_user ON voice_activity(user_id)
        ''')
        
        # Заполняем таблицу типов наказаний
        punishment_types = [
            ('kick', False),
            ('ban', False),
            ('temp_ban', True),
            ('mute', False),
            ('temp_mute', True),
            ('voice_mute', False),
            ('temp_voice_mute', True),
            ('warn', False)
        ]
        
        cursor.executemany('''
        INSERT IGNORE INTO punishment_types (name, is_temporary) 
        VALUES (%s, %s)
        ''', punishment_types)
        
        self.db.commit()

    @tasks.loop(minutes=1)
    async def check_temp_punishments(self):
        cursor = self.db.cursor(dictionary=True)
        now = datetime.utcnow()
        
        cursor.execute('''
        SELECT p.id, p.user_id, pt.name, p.expires_at 
        FROM punishments p
        JOIN punishment_types pt ON p.punishment_type_id = pt.id
        WHERE p.revoked = FALSE 
        AND p.expires_at IS NOT NULL 
        AND p.expires_at <= %s
        ''', (now,))
        
        for punishment in cursor.fetchall():
            guild = self.bot.guilds[0] if self.bot.guilds else None
            if not guild:
                continue
                
            user = guild.get_member(punishment['user_id'])
            action = None
            
            try:
                if punishment['name'] == 'temp_ban':
                    await guild.unban(discord.Object(id=punishment['user_id']))
                    action = "автоматический разбан"
                elif punishment['name'] in ['temp_mute', 'temp_voice_mute']:
                    role_name = "Muted" if punishment['name'] == 'temp_mute' else "Voice Muted"
                    role = discord.utils.get(guild.roles, name=role_name)
                    if role and user and role in user.roles:
                        await user.remove_roles(role)
                    action = f"автоматический размут ({'чат' if punishment['name'] == 'temp_mute' else 'голос'})"
                
                # Помечаем наказание как отозванное
                cursor.execute('''
                UPDATE punishments 
                SET revoked = TRUE, revoked_at = %s, revoked_by = %s
                WHERE id = %s
                ''', (now, self.bot.user.id, punishment['id']))
                
                # Логируем действие
                if action:
                    await self.log_action(
                        user_id=punishment['user_id'],
                        action_type="Автоснятие наказания",
                        details=f"Тип: {punishment['name']}\nПричина: истек срок наказания"
                    )
                    
                    if guild:
                        log_channel = discord.utils.get(guild.channels, name="mod-logs")
                        if log_channel and user:
                            embed = discord.Embed(
                                title=action.capitalize(),
                                description=f"Пользователю {user.mention} снято наказание",
                                color=discord.Color.green(),
                                timestamp=now
                            )
                            embed.add_field(name="Тип наказания", value=punishment['name'])
                            embed.add_field(name="Было назначено до", value=punishment['expires_at'])
                            await log_channel.send(embed=embed)
            
            except Exception as e:
                print(f"Ошибка при автоматическом снятии наказания: {e}")
                continue
        
        self.db.commit()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel != after.channel:
            cursor = self.db.cursor()
            now = datetime.utcnow()
            
            try:
                # Выход из канала
                if before.channel:
                    cursor.execute('''
                    UPDATE voice_activity 
                    SET leave_time = %s, duration_seconds = TIMESTAMPDIFF(SECOND, join_time, %s)
                    WHERE user_id = %s AND leave_time IS NULL
                    ''', (now, now, member.id))
                
                # Вход в канал
                if after.channel:
                    cursor.execute('''
                    INSERT INTO voice_activity 
                    (user_id, channel_id, channel_name, join_time)
                    VALUES (%s, %s, %s, %s)
                    ''', (
                        member.id,
                        after.channel.id,
                        after.channel.name,
                        now
                    ))
                
                self.db.commit()
            except Exception as e:
                print(f"Ошибка при обновлении голосовой активности: {e}")

    async def log_action(self, user_id: int, action_type: str, details: str, guild: Optional[discord.Guild] = None):
        """Улучшенный метод логирования"""
        cursor = self.db.cursor()
        now = datetime.utcnow()
        
        try:
            cursor.execute('''
            INSERT INTO logs (user_id, action_type, details, created_at)
            VALUES (%s, %s, %s, %s)
            ''', (user_id, action_type, details, now))
            
            if guild:
                log_channel = discord.utils.get(guild.channels, name="mod-logs")
                if log_channel:
                    user = guild.get_member(user_id)
                    embed = discord.Embed(
                        title=f"Лог: {action_type}",
                        description=f"**Пользователь:** {user.mention if user else user_id}",
                        color=discord.Color.blue(),
                        timestamp=now
                    )
                    embed.add_field(name="Детали", value=details, inline=False)
                    await log_channel.send(embed=embed)
            
            self.db.commit()
        except Exception as e:
            print(f"Ошибка при логировании: {e}")

    async def update_user_data(self, user: discord.User):
        """Обновление данных пользователя с обработкой ошибок"""
        cursor = self.db.cursor()
        
        try:
            cursor.execute('''
            INSERT INTO users 
            (user_id, username, discriminator, avatar_url, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            discriminator = VALUES(discriminator),
            avatar_url = VALUES(avatar_url)
            ''', (
                user.id,
                user.name,
                user.discriminator,
                str(user.avatar.url) if user.avatar else None,
                user.created_at
            ))
            self.db.commit()
        except Exception as e:
            print(f"Ошибка при обновлении данных пользователя: {e}")

    async def get_punishment_type_id(self, name: str) -> Optional[int]:
        """Получение ID типа наказания"""
        cursor = self.db.cursor(dictionary=True)
        cursor.execute('SELECT id FROM punishment_types WHERE name = %s', (name,))
        result = cursor.fetchone()
        return result['id'] if result else None

    async def apply_punishment(
        self,
        interaction: discord.Interaction,
        user: Union[discord.Member, discord.User],
        action_type: str,
        reason: str,
        duration: Optional[str] = None
    ):
        """Улучшенный метод применения наказаний"""
        try:
            guild = interaction.guild
            moderator = interaction.user
            
            if not guild:
                raise ValueError("Действие должно выполняться на сервере")
            
            await self.update_user_data(user)
            await self.update_user_data(moderator)
            
            # Получаем ID типа наказания
            punishment_type_id = await self.get_punishment_type_id(action_type.lower())
            if not punishment_type_id:
                raise ValueError(f"Неизвестный тип наказания: {action_type}")
            
            # Парсим длительность
            duration_seconds = None
            expires_at = None
            
            if duration:
                duration_seconds = self.parse_duration(duration)
                if not duration_seconds:
                    raise ValueError("Неверный формат длительности. Используйте 1h, 2d, 30m")
                
                expires_at = datetime.utcnow() + timedelta(seconds=duration_seconds)
            
            # Сохраняем в базу данных
            cursor = self.db.cursor()
            cursor.execute('''
            INSERT INTO punishments 
            (user_id, moderator_id, punishment_type_id, reason, duration_seconds, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                user.id,
                moderator.id,
                punishment_type_id,
                reason,
                duration_seconds,
                expires_at
            ))
            
            # Применяем действие
            result = await self.execute_punishment_action(
                guild=guild,
                user=user,
                moderator=moderator,
                action_type=action_type,
                punishment_type_id=punishment_type_id,
                reason=reason,
                expires_at=expires_at
            )
            
            self.db.commit()
            
            # Логируем и отправляем подтверждение
            await self.handle_punishment_response(
                interaction, user, moderator, action_type, reason, 
                duration, result, expires_at
            )
            
        except Exception as e:
            await self.handle_punishment_error(interaction, e)

    def parse_duration(self, duration_str: str) -> Optional[int]:
        """Парсинг строки длительности в секунды"""
        match = re.match(r"^(\d+)([hdm])$", duration_str)
        if not match:
            return None
        
        num, unit = match.groups()
        num = int(num)
        
        if unit == 'h':
            return num * 3600
        elif unit == 'd':
            return num * 86400
        elif unit == 'm':
            return num * 60
        return None

    async def execute_punishment_action(
        self,
        guild: discord.Guild,
        user: Union[discord.Member, discord.User],
        moderator: discord.Member,
        action_type: str,
        punishment_type_id: int,
        reason: str,
        expires_at: Optional[datetime]
    ) -> str:
        """Выполнение конкретного действия наказания"""
        result = ""
        
        if action_type == 'kick':
            await user.kick(reason=reason)
            result = f"Пользователь {user.mention} был кикнут."
        
        elif action_type == 'ban':
            await user.ban(reason=reason)
            result = f"Пользователь {user.mention} был забанен."
        
        elif action_type == 'temp_ban':
            await user.ban(reason=f"{reason} | До: {expires_at}")
            result = f"Пользователь {user.mention} временно забанен до {expires_at.strftime('%Y-%m-%d %H:%M')}."
        
        elif action_type in ['mute', 'temp_mute']:
            mute_role = await self.get_or_create_role(guild, "Muted")
            await user.add_roles(mute_role, reason=reason)
            result = f"Пользователь {user.mention} получил {'временный ' if action_type == 'temp_mute' else ''}чат мут."
            if action_type == 'temp_mute':
                result += f" До: {expires_at.strftime('%Y-%m-%d %H:%M')}"
        
        elif action_type in ['voice_mute', 'temp_voice_mute']:
            vmute_role = await self.get_or_create_role(guild, "Voice Muted")
            await user.add_roles(vmute_role, reason=reason)
            result = f"Пользователь {user.mention} получил {'временный ' if action_type == 'temp_voice_mute' else ''}голосовой мут."
            if action_type == 'temp_voice_mute':
                result += f" До: {expires_at.strftime('%Y-%m-%d %H:%M')}"
        
        elif action_type == 'unban':
            await guild.unban(user, reason=reason)
            result = f"Пользователь {user.mention} был разбанен."
        
        elif action_type == 'unmute':
            mute_role = discord.utils.get(guild.roles, name="Muted")
            vmute_role = discord.utils.get(guild.roles, name="Voice Muted")
            
            if mute_role and mute_role in user.roles:
                await user.remove_roles(mute_role, reason=reason)
            if vmute_role and vmute_role in user.roles:
                await user.remove_roles(vmute_role, reason=reason)
            
            result = f"Пользователь {user.mention} был размучен."
        
        elif action_type == 'warn':
            cursor = self.db.cursor()
            punishment_type_id = await self.get_punishment_type_id('warn')
            
            cursor.execute('''
            INSERT INTO punishments 
            (user_id, moderator_id, punishment_type_id, reason)
            VALUES (%s, %s, %s, %s)
            ''', (
                user.id,
                moderator.id,
                punishment_type_id,
                reason
            ))
            
            result = f"Пользователь {user.mention} получил предупреждение."
        
        return result

    async def get_or_create_role(self, guild, role_name):
        """Получает или создает роль с нужными правами"""
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name)
            
            # Настраиваем права для роли
            for channel in guild.channels:
                try:
                    if isinstance(channel, discord.TextChannel) and role_name == "Muted":
                        await channel.set_permissions(role, send_messages=False)
                    elif isinstance(channel, discord.VoiceChannel) and role_name == "Voice Muted":
                        await channel.set_permissions(role, speak=False)
                except discord.Forbidden:
                    continue
        
        return role

    async def handle_punishment_response(self, interaction, user, moderator, action_type, reason, duration, result, expires_at):
        """Обработка ответа после применения наказания"""
        # Логируем действие
        log_details = (
            f"**Модератор:** {moderator.mention}\n"
            f"**Причина:** {reason}\n"
            + (f"**Длительность:** {duration}\n" if duration else "")
        )
        
        await self.log_action(
            user_id=user.id,
            action_type=action_type.replace('_', ' ').title(),
            details=log_details,
            guild=interaction.guild
        )
        
        # Отправляем подтверждение модератору
        embed = discord.Embed(
            title=f"Действие выполнено: {action_type.replace('_', ' ').title()}",
            description=result,
            color=discord.Color.green() if action_type.startswith('un') else discord.Color.red()
        )
        embed.add_field(name="Причина", value=reason, inline=False)
        if duration:
            embed.add_field(name="Длительность", value=duration, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Уведомляем пользователя (если возможно)
        try:
            notify_embed = discord.Embed(
                title=f"К вам применено действие: {action_type.replace('_', ' ').title()}",
                color=discord.Color.red()
            )
            notify_embed.add_field(name="Причина", value=reason, inline=False)
            if duration:
                notify_embed.add_field(name="Длительность", value=duration, inline=False)
            notify_embed.add_field(name="Модератор", value=moderator.mention, inline=False)
            
            await user.send(embed=notify_embed)
        except discord.Forbidden:
            pass

    async def handle_punishment_error(self, interaction, error):
        """Обработка ошибок при применении наказаний"""
        error_embed = discord.Embed(
            title="Ошибка",
            description=f"Не удалось выполнить действие: {str(error)}",
            color=discord.Color.red()
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
        except:
            await interaction.channel.send(embed=error_embed)

    @commands.slash_command(name="mod", description="Модераторские команды")
    async def mod(self, ctx):
        """Группа модераторских команд"""
        pass

    @mod.sub_command(name="action", description="Действия с пользователем")
    async def mod_action(self, ctx, user: discord.member):
        """Действия с пользователем"""
        await self.update_user_data(user)
        view = ModeratorActionsView(user)
        embed = discord.Embed(
            title=f"Действия с пользователем {user.display_name}",
            description="Выберите действие из меню ниже:",
            color=discord.Color.blue()
        )
        await ctx.respond(embed=embed, view=view)

    @mod.sub_command(name="history", description="История пользователя")
    async def mod_history(self, ctx, user: discord.member):
        """Просмотр истории пользователя с пагинацией"""
        await self.update_user_data(user)
        cursor = self.db.cursor(dictionary=True)
        
        # Получаем данные пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user.id,))
        user_data = cursor.fetchone()
        
        # Получаем наказания
        cursor.execute('''
        SELECT pt.name, p.reason, p.expires_at, p.created_at 
        FROM punishments p
        JOIN punishment_types pt ON p.punishment_type_id = pt.id
        WHERE p.user_id = %s 
        ORDER BY p.created_at DESC
        LIMIT 5
        ''', (user.id,))
        punishments = cursor.fetchall()
        
        # Получаем голосовую активность
        cursor.execute('''
        SELECT channel_name, join_time, leave_time 
        FROM voice_activity 
        WHERE user_id = %s 
        ORDER BY join_time DESC 
        LIMIT 5
        ''', (user.id,))
        voice_activity = cursor.fetchall()
        
        # Создаем embed
        embed = discord.Embed(
            title=f"История пользователя {user.display_name}",
            description=f"ID: {user.id}\nАккаунт создан: {user.created_at.strftime('%Y-%m-%d')}",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Добавляем наказания
        if punishments:
            pun_text = []
            for p in punishments:
                line = f"**{p['name'].replace('_', ' ').title()}**: {p['reason']}"
                if p['expires_at']:
                    line += f" (до {p['expires_at'].strftime('%Y-%m-%d %H:%M')})"
                line += f"\n{p['created_at'].strftime('%Y-%m-%d')}"
                pun_text.append(line)
            
            embed.add_field(
                name=f"Последние наказания ({len(punishments)})",
                value="\n\n".join(pun_text),
                inline=False
            )
        else:
            embed.add_field(name="Наказания", value="Нет данных", inline=False)
        
        # Добавляем голосовую активность
        if voice_activity:
            voice_text = []
            for v in voice_activity:
                join_time = v['join_time'].strftime('%Y-%m-%d %H:%M')
                leave_time = v['leave_time'].strftime('%Y-%m-%d %H:%M') if v['leave_time'] else "В канале"
                voice_text.append(f"**{v['channel_name']}**: {join_time} - {leave_time}")
            
            embed.add_field(
                name="Голосовая активность (последние 5)",
                value="\n".join(voice_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Голосовая активность",
                value="Нет данных",
                inline=False
            )
        
        await ctx.respond(embed=embed)

class ModeratorActionsView(discord.ui.View):
    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.add_item(ModeratorActionSelect(user=self.user))

class ModeratorActionSelect(discord.ui.Select):
    def __init__(self, user):
        self.user = user
        options = [
            discord.SelectOption(label="Kick", value="kick", description="Кикнуть пользователя"),
            discord.SelectOption(label="Temp Ban", value="temp_ban", description="Временный бан пользователя"),
            discord.SelectOption(label="Ban", value="ban", description="Забанить пользователя"),
            discord.SelectOption(label="Temp Voice Mute", value="temp_voice_mute", description="Временный мут в голосовых"),
            discord.SelectOption(label="Voice Mute", value="voice_mute", description="Мут в голосовых"),
            discord.SelectOption(label="Temp Mute", value="temp_mute", description="Временный мут в чате"),
            discord.SelectOption(label="Mute", value="mute", description="Мут в чате"),
            discord.SelectOption(label="Unban", value="unban", description="Разбанить пользователя"),
            discord.SelectOption(label="Unmute", value="unmute", description="Размутить пользователя"),
            discord.SelectOption(label="Warn", value="warn", description="Выдать предупреждение")
        ]
        super().__init__(
            placeholder="Выберите действие",
            options=options,
            custom_id="action_select"
        )

    async def callback(self, interaction: discord.Interaction):
        modal = ModeratorActionModal(
            user=self.user,
            action=self.values[0]
        )
        await interaction.response.send_modal(modal)

class ModeratorActionModal(discord.ui.Modal):
    def __init__(self, user, action, *args, **kwargs):
        self.user = user
        self.action = action
        super().__init__(
            title=f"{action.replace('_', ' ').title()} - {user.display_name}",
            *args,
            **kwargs
        )
        
        self.reason = discord.ui.TextInput(
            label="Причина",
            style=discord.TextStyle.long,
            placeholder="Укажите причину действия",
            required=True
        )
        self.add_item(self.reason)
        
        if action.startswith("temp"):
            self.duration = discord.ui.TextInput(
                label="Длительность (1h, 2d, 30m)",
                placeholder="Пример: 1h (1 час), 2d (2 дня), 30m (30 минут)",
                required=True
            )
            self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value
        duration = getattr(self, 'duration', None)
        duration = duration.value if duration else None
        
        await Moderator.apply_punishment(
            self,
            interaction=interaction,
            user=self.user,
            action_type=self.action,
            reason=reason,
            duration=duration
        )

async def setup(bot):
    await bot.add_cog(Moderator(bot))