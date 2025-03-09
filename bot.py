import discord
import os
import random
import json
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Spotify setup
client_credentials_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/sotd ", intents=intents, help_command=None)

# Local storage for songs and settings
DATA_FILE = "sotd_data.json"

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

if "servers" not in data:
    data["servers"] = {}

def get_server_data(guild_id):
    if str(guild_id) not in data["servers"]:
        data["servers"][str(guild_id)] = {"songs": [], "daily_time": None, "timezone": 0, "post_channel": None, "ping_roles": [], "config_roles": []}
    return data["servers"][str(guild_id)]

def has_config_role(interaction):
    server_data = get_server_data(interaction.guild.id)
    config_roles = server_data.get("config_roles", [])
    if not config_roles:
        return True  # If no config roles are set, allow all users to configure
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in user_roles for role_id in config_roles)

# Help command
@bot.tree.command(name="help", description="Shows the list of available commands")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Song of the Day - Commands", color=discord.Color.blue())
    embed.add_field(name="🎵 **Adding Songs**", value="`/sotd add track <name>`\n`/sotd add album <name>`\n`/sotd add artist <name>`\n`/sotd add playlist <name>`", inline=False)
    embed.add_field(name="📜 **Viewing Songs**", value="`/sotd showlist` - Shows all added songs\n`/sotd clearlist` - Clears all added songs", inline=False)
    embed.add_field(name="⚙️ **Setup & Settings**", value="`/sotd setup <time> <timezone> <#channel> <@role>` - Sets daily post time and ping role\n`/sotd configroles @role1 @role2` - Chooses roles that can configure settings\n`/sotd testpost` - Sends a test Song of the Day post\n`/sotd debugtest` - Sends a message for testing purposes", inline=False)
    embed.add_field(name="🛑 **Uninstall**", value="`/sotd uninstall` - Deletes all settings and songs", inline=False)
    embed.set_footer(text="Use /sotd before each command!")
    await interaction.response.send_message(embed=embed)

# Show list command
@bot.tree.command(name="showlist", description="Shows the list of added songs")
async def showlist(interaction: discord.Interaction):
    server_data = get_server_data(interaction.guild.id)
    songs = server_data["songs"]

    if not songs:
        await interaction.response.send_message(":x: The song list is empty! Use `/sotd add` to add songs. 🎵")
        return

    page_size = 15
    pages = [songs[i:i + page_size] for i in range(0, len(songs), page_size)]
    total_pages = len(pages)
    current_page = 0

    def format_page(page):
        return "\n".join([f"{i+1}. [{song['name']}]({song['url']})" for i, song in enumerate(page)])

    embed = discord.Embed(title="🎶 Song List", description=format_page(pages[current_page]), color=0x1DB954)
    embed.set_footer(text=f"Page {current_page + 1} of {total_pages}")

    message = await interaction.response.send_message(embed=embed)
    if total_pages > 1:
        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")

        def check(reaction, user):
            return user == interaction.user and reaction.message.id == message.id and reaction.emoji in ["⬅️", "➡️"]

        while True:
            try:
                reaction, user = await bot.wait_for("reaction_add", timeout=60.0, check=check)
                if reaction.emoji == "⬅️" and current_page > 0:
                    current_page -= 1
                elif reaction.emoji == "➡️" and current_page < total_pages - 1:
                    current_page += 1
                else:
                    await message.remove_reaction(reaction.emoji, user)
                    continue
                
                embed.description = format_page(pages[current_page])
                embed.set_footer(text=f"Page {current_page + 1} of {total_pages}")
                await message.edit(embed=embed)
                await message.remove_reaction(reaction.emoji, user)
            except:
                break

# Add track, album, artist, playlist
@bot.tree.command(name="add", description="Adds a track, album, artist, or playlist")
@app_commands.describe(search_type="Type of search (track, album, artist, playlist)", search_query="Search query")
async def add(interaction: discord.Interaction, search_type: str, search_query: str):
    server_data = get_server_data(interaction.guild.id)
    search_type = search_type.lower()

    if search_type not in ['track', 'album', 'playlist', 'artist']:
        await interaction.response.send_message(":x: Invalid type! Use `track`, `album`, `playlist`, or `artist`. :thinking:")
        return
    
    results = sp.search(q=search_query, type=search_type)
    if not results[f'{search_type}s']['items']:
        await interaction.response.send_message(":x: Couldn't find anything! :broken_heart:")
        return
    
    item = results[f'{search_type}s']['items'][0]
    item_name = item['name']
    item_url = item['external_urls']['spotify']
    added_songs = []

    if search_type == "album":
        album_tracks = sp.album_tracks(item['id'])['items']
        for track in album_tracks:
            track_name = f"{track['name']} (from {item_name})"
            track_url = track['external_urls']['spotify']
            server_data["songs"].append({"name": track_name, "url": track_url})
            added_songs.append(track_name)

    elif search_type == "artist":
        artist_albums = sp.artist_albums(item['id'], album_type='album')['items']
        for album in artist_albums:
            album_tracks = sp.album_tracks(album['id'])['items']
            for track in album_tracks:
                track_name = f"{track['name']} (from {album['name']})"
                track_url = track['external_urls']['spotify']
                server_data["songs"].append({"name": track_name, "url": track_url})
                added_songs.append(track_name)

    else:
        server_data["songs"].append({"name": item_name, "url": item_url})
        added_songs.append(item_name)
    
    save_data(data)

    embed = discord.Embed(title="✅ Songs Added!", color=discord.Color.green())
    embed.description = "\n".join([f"🎵 **{song}**" for song in added_songs])
    await interaction.response.send_message(embed=embed)

# Config roles
@bot.tree.command(name="configroles", description="Sets roles that can configure the bot")
@app_commands.describe(roles="Roles that can configure the bot")
async def configroles(interaction: discord.Interaction, roles: discord.Role):
    server_data = get_server_data(interaction.guild.id)
    server_data["config_roles"] = [role.id for role in roles]  # NOW STORES CONFIG ROLES, NOT PING ROLES
    save_data(data)
    
    embed = discord.Embed(title="✅ Config Roles Set!", description="These roles can now configure the bot:", color=discord.Color.green())
    embed.description += "\n" + "\n".join([role.mention for role in roles])
    await interaction.response.send_message(embed=embed)

# Uninstall command
@bot.tree.command(name="uninstall", description="Uninstalls the bot and deletes all data")
async def uninstall(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id in data["servers"]:
        del data["servers"][guild_id]
        save_data(data)
        embed = discord.Embed(title="🗑️ Bot uninstalled.", description="All data for this server has been deleted.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title="⚠️ Bot not installed.", description="There is no data to delete.", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

# Clear list command
@bot.tree.command(name="clearlist", description="Clears all songs from the list")
async def clearlist(interaction: discord.Interaction):
    """Clears all songs from the list."""
    if not has_config_role(interaction):
        await interaction.response.send_message(":x: You do not have permission to clear the song list.")
        return

    server_data = get_server_data(interaction.guild.id)
    
    if not server_data["songs"]:
        embed = discord.Embed(title="⚠️ Song List is Already Empty!", description="There's nothing to clear...", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)
        return
    
    server_data["songs"] = []  # Clears the list
    save_data(data)

    embed = discord.Embed(title="🗑️ Song List Cleared!", description="All songs have been removed. ✨", color=discord.Color.red())
    await interaction.response.send_message(embed=embed)

# Daily song posting
@tasks.loop(minutes=1)
async def daily_song():
    now = datetime.now(timezone.utc)
    for guild_id, settings in data["servers"].items():
        if settings["daily_time"] is None or settings["post_channel"] is None:
            continue
        
        post_time = settings["daily_time"]
        post_hour, post_minute = map(int, post_time.split(":"))
        
        if now.hour == post_hour and now.minute == post_minute:
            if settings["songs"]:
                random_song = random.choice(settings["songs"])
                channel = bot.get_channel(settings["post_channel"])
                embed = discord.Embed(title="🎶 Song of the Day!", description=f"**{random_song['name']}**", color=discord.Color.pink())
                
                if channel:
                    if settings["ping_roles"]:
                        role_mentions = " ".join([f"<@&{role_id}>" for role_id in settings["ping_roles"]])
                        await channel.send(role_mentions, embed=embed)
                        await channel.send(f"🎵 [Listen on Spotify]({random_song['url']}) 🎵")  # Send the Spotify URL in the desired format
                    else:
                        await channel.send(embed=embed)
                        await channel.send(f"🎵 [Listen on Spotify]({random_song['url']}) 🎵")  # Send the Spotify URL in the desired format
                    
                    # Remove the song from the list after posting
                    settings["songs"].remove(random_song)
                    save_data(data)

# Setup command
@bot.tree.command(name="setup", description="Sets up the daily song posting")
@app_commands.describe(daily_time="Daily post time (HH:MM)", timezone_offset="Timezone offset", channel="Channel to post in", ping_role="Role to ping")
async def setup(interaction: discord.Interaction, daily_time: str, timezone_offset: int, channel: discord.TextChannel, ping_role: discord.Role):
    if not has_config_role(interaction):
        await interaction.response.send_message(":x: You do not have permission to configure the bot.")
        return

    server_data = get_server_data(interaction.guild.id)
    server_data["daily_time"] = daily_time
    server_data["timezone"] = timezone_offset
    server_data["post_channel"] = channel.id
    server_data["ping_roles"] = [ping_role.id]  # NOW CORRECTLY STORES PING ROLES
    save_data(data)

    embed = discord.Embed(title="✅ Setup Complete!", color=discord.Color.green())
    embed.description = f"**Time:** {daily_time} UTC+{timezone_offset}\n**Channel:** {channel.mention}\n**Ping Role:** {ping_role.mention}"
    await interaction.response.send_message(embed=embed)

# Test post command
@bot.tree.command(name="testpost", description="Sends a test Song of the Day post")
async def testpost(interaction: discord.Interaction):
    now = datetime.now(timezone.utc)
    for guild_id, settings in data["servers"].items():
        if settings["post_channel"] is None:
            continue
        
        if settings["songs"]:
            random_song = random.choice(settings["songs"])
            channel = bot.get_channel(settings["post_channel"])
            embed = discord.Embed(title="🎶 Test Song of the Day!", description=f"**{random_song['name']}**", color=discord.Color.pink())
            
            if channel:
                if settings["ping_roles"]:
                    role_mentions = " ".join([f"<@&{role_id}>" for role_id in settings["ping_roles"]])
                    await channel.send(role_mentions, embed=embed)
                    await channel.send(f"🎵 [Listen on Spotify]({random_song['url']}) 🎵")  # Send the Spotify URL in the desired format
                else:
                    await channel.send(embed=embed)
                    await channel.send(f"🎵 [Listen on Spotify]({random_song['url']}) 🎵")  # Send the Spotify URL in the desired format
                
                # Remove the song from the list after posting
                settings["songs"].remove(random_song)
                save_data(data)

# Debug test command
@bot.tree.command(name="debugtest", description="Sends a test message to check permissions and message sending")
async def debugtest(interaction: discord.Interaction):
    embed = discord.Embed(title="🔧 Debug Test", description="This is a test message to check permissions and message sending. I can text here! :tada:", color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync()
    daily_song.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(ctx, discord.Interaction):
        if isinstance(error, app_commands.CommandNotFound):
            await ctx.response.send_message(":x: Sorry, that command does not exist! Use `/sotd help` to see the list of available commands.")
        else:
            await ctx.response.send_message(f":x: Sorry, something happened! {str(error)}")
    else:
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(":x: Sorry, that command does not exist! Use `/sotd help` to see the list of available commands.")
        else:
            await ctx.send(f":x: Sorry, something happened! {str(error)}")

bot.run(TOKEN)