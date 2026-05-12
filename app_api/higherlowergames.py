import sys
import os
import io
import asyncio

import urllib.request
from dotenv import load_dotenv
from PIL import Image

import requests
import requests_async
from bs4 import BeautifulSoup

from alive_progress import alive_bar

from pymongo import MongoClient
from pydantic import BaseModel, Field

from rich import print

# import steam
from steam.client import SteamClient
from steam.client.cdn import CDNClient
from steam.enums.common import EResult


# Loads environment variable
load_dotenv(".env")

# --help display
HELP_MSG = \
"""higherlowergames [b]<command>[/b]

Comands:
[b]seed or s[/b]        - Seeds the database
[b]update or u[/b]      - Updates the database
"""


# MongoDB config
MONGO_HOST = os.getenv('DB_HOST') or '127.0.0.1'
MONGODB_URI = f'mongodb://{MONGO_HOST}'
DB_NAME = 'higherlower-game'

# Used in non-anon login
# fill in personal login
STEAM_USERNAME = os.getenv('STEAM_USERNAME') or ''
STEAM_PASSWORD = os.getenv('STEAM_PASSWORD') or ''

# This is required for seeding. 
# Can be requested here: https://steamcommunity.com/dev
# After receiving one, it can be re-viewed at: https://steamcommunity.com/dev/apikey
STEAM_API_KEY = os.getenv('STEAM_API_KEY') or ''
# print(STEAM_API_KEY)

# Map of known Steam CDN image urls
# replace {appId} with a Steam app's ID
# NOTE that not all Steam apps have every kind of image
# source: https://gaming.stackexchange.com/questions/359614/is-there-a-way-to-download-the-box-art-for-steam-games#:~:text=Other%20Art%20Formats:%20Beyond%20the%20main%20box,using%20URLs%20like:%20https://steamcdn-a.akamaihd.net/steam/apps/255220/header.jpg%2C%20https://steamcdn-a.akamaihd.net/steam/apps/255220/logo.png%2C%20and%20https://steamcdn-a.akamaihd.net/steam/apps/255220/library_hero.jpg.
STEAMCDN_IMAGE_URLS = {
    # I've yet to verify this works for any app, most I've tried return 404
    'logo': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/logo.jpg',
    
    # Ultra-wide view
    'libraryHero': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/library_hero.jpg',

    # I think these are generated for Steam store page?
    'pageBgGenerated': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/page_bg_generated.jpg',

    # A comment from source claims this is the "washed out" banner of Steam community pages
    'pageBgGeneratedv6b': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/page_bg_generated_v6b.jpg',
    
    # This one's ideal for main app's mobile view
    'header': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/header.jpg',
    
    # This one's ideal for the main app's desktop view
    '600x900_2x': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/library_600x900_2x.jpg',

    # ^ except lower resolution; source says it's actually 300x450
    '600x900': 'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/library_600x900.jpg',
}

# Manifests with these in their name are ignored when calculating file size.
DEPOT_MANIFEST_BLACKLIST:set[str] = {'beta', 'alpha', 'test'}


# Model for steamapps collection
class SteamApp(BaseModel):
    # NOTE This can't be an alis for _id since it isn't always unique
    appId: int
    appType: str = ''
    baselanguage: str = ''

    # Maps language to application names
    names: dict[str, str] = Field(default_factory={})

    # Maps imageType (See STEAM_CDN_IMAGE_URLS) to their url
    images: dict[str, str] = Field(default={})
    
    # Assumes Windows, English, and no DLC
    # TODO/TBD store as map for different baselanguages? I'm
    # unsure of whether there's a large filesize difference between languages
    # for most games though
    totalSize: int = 0      # Final uncompressed size of installed game
    downloadSize: int = 0   # Size of Steam download

    # Bonus
    dlcSize: int = 0
    dlcDownloadSize: int = 0
    
    timeUpdated: int = -1


def login(anon:bool=False) -> EResult:
    if STEAM_CLIENT.logged_on:
        return EResult.OK
    
    # enum CMsgClientLogonResponse.eresult
    # https://github.com/ValvePython/steam/blob/513c68ca081dc9409df932ad86c66100164380a6/protobufs/steammessages_clientserver.proto#L95-L118
    print('Logging in. . .', end='\n' if not anon else '')
    if not anon and (STEAM_USERNAME and STEAM_PASSWORD):
        return STEAM_CLIENT.cli_login(username=STEAM_USERNAME, password=STEAM_PASSWORD)

    # Anonymous login
    eres = STEAM_CLIENT.anonymous_login()
    if eres is EResult.OK:
        print(f'[green]{eres.name}')
    else:
        print(f'[red]{eres.name}')
    
    return eres


def get_cdn() -> CDNClient:
    if not STEAM_CLIENT.logged_on and login() != EResult.OK:
        return
    return CDNClient(STEAM_CLIENT)


def get_box_image(appId:int, silent:bool=True):
    """Depreciated"""
    
    URL_ATTEMPT_CHAIN:list[str] = [
        'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/library_600x900_2x.jpg',
        'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/library_600x900.jpg',
        'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/logo.jpg',
        'https://steamcdn-a.akamaihd.net/steam/apps/{appId}/header.jpg',
    ]
    IMG_FOLDER = r'E:\Coding\Web Dev\higherlower_games\public\images'
    
    path = os.path.join(IMG_FOLDER, str(appId) + '.jpg')
    if os.path.exists(path):
        if not silent: print(f'[yellow]{appId} already has a box image')
        return
    
    urlopen = None
    for url in URL_ATTEMPT_CHAIN:
        try: 
            urlopen = urllib.request.urlopen(url.format(appId=appId)).read()
        except Exception:
            urlopen = None
        
        if urlopen: break
    
    if not urlopen:
        if not silent: print(f'[red]Failed to find a valid box image')
        return
    
    img = Image.open(io.BytesIO(urlopen))
    
    try:
        img.save(path)
    except Exception as e:
        if not silent: print(f'[red]Failed to save box image for {appId}: {e}')


async def getAppImageUrls(appId:int) -> dict[str, str]:
    """Scans Steam's CDN for urls which 
    return images for the given appId.

    Args:
        appId (int): SteamApp ID

    Returns:
        dict[str,str]: map of {imageType, url} for each valid image.
        See STEAMCDN_IMAGE_URLS for info on imageType's.
    """
    
    # Requests image from each known url
    # print(f"Scanning SteamCDN for appId-{appId} images:")
    urls:dict[str, str] = {}
    for imageType, url in STEAMCDN_IMAGE_URLS.items():
        formattedUrl = url.format(appId=appId)
        res = await requests_async.get(formattedUrl)
        
        if not res: continue

        # Validates that res contains an image
        # res.content should be a byte array of image data
        try:
            Image.open(io.BytesIO(res.content))
        except Exception as e:
            # print(f"\t{imageType} scanned failed due to exception {e}")
            continue
        
        urls[imageType] = formattedUrl

    return urls


async def collectAppImageUrls(apps:list[SteamApp], maxTasks:int = 20) -> list[SteamApp]:
    """Collects image URLs for a list of SteamApps asynchronously. **NOTE**
    this can take a while for larger lists.

    Args:
        apps (list[SteamApp]): List of SteamApps to collect images for
    """
    
    # per-app task
    async def processApp(app: SteamApp) -> None:
        # print("Collecting images for " + list(app.names.values())[0])
        app.images = await getAppImageUrls(app.appId)
        # print("Collection finished for " + list(app.names.values())[0])
        return app

    # Running tasks for each app's requests
    out:list[SteamApp] = []
    with alive_bar(len(apps), title="Collecting app images") as bar:
        async with asyncio.TaskGroup() as tg:
            queue = apps
            tasks:list[asyncio.Task] = []

            # Task finish callback which cycles tasks
            # and appends processed apps to out list
            def onTaskFinished(t: asyncio.Task) -> None:
                try:
                    app = t.result()
                    # print(f'[Callback] Finished processing {list(app.names.values())[0]}')
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"[Callback] Unhandled exception: {e}")
                    return
                
                # Updating task queue
                tasks.remove(t)
                if len(queue) > 0:
                    nextApp = queue.pop(0)

                    # print(f'[Callback] Beginning task for {list(nextApp.names.values())[0]}')
                    task = tg.create_task(processApp(nextApp))
                    task.add_done_callback(onTaskFinished)
                    tasks.append(task)

                # Adding app to output
                out.append(app)
                bar()
                
                # DEBUG
                if not ( app.images ): 
                    # print(f"[Callback] task failed: {t}")
                    pass
                
            # Initial task queue
            for _ in range(max(1, maxTasks)):
                if len(queue) <= 0: break
                nextApp = queue.pop(0)

                # print(f'[Callback] Beginning task for {list(nextApp.names.values())[0]}')
                task = tg.create_task(processApp(nextApp))
                task.add_done_callback(onTaskFinished)
                tasks.append(task)
            
            # Beginning task(s)
            # This should trigger a chain of task completion(s)
            await asyncio.wait(tasks)
    
    return out


def get_packages(appId:int) -> set[int]:
    res = requests.get('https://store.steampowered.com/app/{appId}'.format(appId=appId))
    if not res:
        # print(f'[red]Failed to get webpage: {res}')
        return []

    soup = BeautifulSoup(res.content, 'html.parser')
    if not soup:
        # print(f'[red]Failed to create soup')
        return []
    
    packages:set[int] = set()
    for tag in soup.find_all('form', action='https://store.steampowered.com/cart/', method='POST'):
        if 'add_to_cart' not in tag['name']:
            continue
        
        hidden = tag.find(lambda t2: t2['name'] == 'subid')
        if not hidden:
            # print('Could not find hidden input tag with sub id')
            continue
        
        packages.add(int(hidden['value']))

    return packages


def parse_size(
        prod_info:dict, 
        baselanguage:str='english', 
        silent:bool=True
) -> tuple[int, int, int, int]:
    """Parses file sizes from an app's product info.

    Args:
        prod_info (dict): Product info dictionary: values of SteamClient.get_product_info()['apps']
        baselanguage (str, optional): Base language of application. Defaults to 'english'.
        silent (bool, optional): Won't print to console. Defaults to True.

    Returns:
        tuple[int, int, int, int]: totalSize, downloadSize, dlcSize, and dlcDownloadSize
    """
    
    totalSize:int          = 0
    downloadSize:int       = 0
    dlcSize:int            = 0
    dlcDownloadSize:int   = 0
    
    if not silent: 
        # print('\t-> Checking depot info')
        pass
    
    for k, v in prod_info.get('depots', {}).items():
        # Depots are keyed with their depot id
        if not k.isdigit(): 
            # if not silent: print(f'\t\t{k}[yellow] - Non digit key')
            continue

        # They also have 'manifests' which are lists of the files inside them
        if 'manifests' not in v: 
            # if not silent: print(f'\t\t{k}[yellow] - Missing manifests')
            continue
        
        # Config filters
        if 'config' in v:
            # Skipping non-Windows
            oslist = v['config'].get('oslist')
            if oslist and 'windows' not in oslist:
                # if not silent: print(f'\t\t{k}[yellow] - Non-windows')
                continue
            
            # Skipping defined, non-baselanguage
            lang = v['config'].get('language', '')
            if lang and lang not in baselanguage:
                # if not silent: print(f'\t\t{k}[yellow] - Non-{baselanguage.capitalize()} language: {lang}')
                continue
        
        # Summing manifests sizes
        # if not silent: print(f'\t\t{k} - Reading manifests')
        for man_id, info, in v['manifests'].items():
            # Skipping blacklisted manifest ids
            blacklist_trigger:str = ''
            for token in DEPOT_MANIFEST_BLACKLIST:
                if token.lower() in man_id.lower(): 
                    blacklist_trigger = token
                    break
            
            if blacklist_trigger != '':
                if not silent:
                    # print(f'\t\t\t{man_id}[red] - Blacklisted by token \'{blacklist_trigger}\'')
                    pass
                continue
            
            if any([token.lower() in man_id for token in DEPOT_MANIFEST_BLACKLIST]):
                if not silent: 
                    # print(f'\t\t\t{man_id}[yellow] - Skipped as blacklisted')
                    pass
                continue
            
            # Adding DLC
            if 'dlcappid' in v:
                # if not silent: print(f'\t\t\t{man_id}[green] - Added to dlcSize')
                dlcSize +=             int( info.get('size', 0) )
                dlcDownloadSize +=    int( info.get('download', 0) )
            
            # Regular depots
            else:
                # if not silent: print(f'\t\t\t{man_id}[green]- Added to file size')
                totalSize +=           int( info['size'] )
                downloadSize +=        int( info['download'] )
        
    return totalSize, downloadSize, dlcSize, dlcDownloadSize


def parse_product_info(appPack: dict, silent:bool = True) -> SteamApp:
    """Creates a SteamApp from an app_info dictionary returned from SteamClient.get_product_info.

    Args:
        appPack (dict): {appId: app_info} dictionary returned from SteamClient.get_product_info.
        silent (bool, optional): Won't print to console. Defaults to True.
    """
    
    # First key should be an app id
    if not (len(appPack.keys()) == 1 and isinstance(list(appPack.keys())[0], int)):
        if not silent: print(f'\t[red]Invalid keys; must be only 1 appId')
        return
    
    # Should only be 1 value: a dict
    if not ( len(appPack.values()) == 1 and isinstance(list(appPack.values())[0], dict) ):
        if not silent: print('\t[red]Invalid value; must be 1 dict of app info')
        return
    
    # Splitting data
    appId = list(appPack.keys())[0]
    # if not silent: print(f'> {appId}')

    prod_info = list(appPack.values())[0]
    
    # Approximates total game size by filtering for Windows, English, and no DLC
    totalSize = 0
    downloadSize = 0
    dlcSize = 0
    dlcDownloadSize = 0
    baselanguage = prod_info \
        .get('depots', {}) \
        .get('baselanguages', 'english')
    
    # Reading depots for file sizes
    if 'depots' in prod_info.keys():
        totalSize, downloadSize, dlcSize, dlcDownloadSize = parse_size(prod_info, baselanguage, silent)
        
    elif not silent:
        # print('\t[red] - Missing \'depots\' entry')
        # print(prod_info.keys())
        pass
    
    # Reading other app info like name and images    
    names = {}
    # icon = ''
    # lib_assets = LibraryAssets()
    
    if common := prod_info.get('common', {}):
        names = { baselanguage: common.get('name', '') }

        # Getting names in different localizations
        for lang, name in common.get('name_localized', {}).items():
            names[lang] = name
    
    if not silent:
        if any(names.values()):
            # print(f'\t[green] - Found names {names}')
            pass
        else:
            # print(f'\t[red] - Failed to find names')
            pass
    
    # Building model
    try:
        app = SteamApp(
            appId=appId,
            appType=prod_info.get('common', {}).get('type', ''),
            version='',
            names=names,
            # icon=icon,
            # lib_assets=lib_assets,
            baselanguage=baselanguage,
            totalSize=totalSize,
            downloadSize=downloadSize,
            dlcSize=dlcSize,
            dlcDownloadSize=dlcDownloadSize,
            timeUpdated=prod_info
                .get('depots', {})
                .get('branches', {})
                .get('public', {})
                .get('timeupdated', -1)
                # TODO instead of -1, use system time?
        )
    except Exception as e:
        print(f'\t[red]Unhandled Exception: {e}')
        return
    
    return app


def parse_products(
        appIds: list[int],
        targetTypes: list[str] = [],
        metaDataOnly:bool=False, 
        silent:bool = True,
        include_undef_type:bool = False,
        anon:bool=False
) -> list[SteamApp]:
    """Parses SteamApp objects from a list of app ids.

    Args:
        appIds (list[int]): Steam app ids
        targetTypes (list[str], optional): Filters apps outside these types when set. Defaults to [].
        metaDataOnly (bool, optional): Will only return metadata. Defaults to False.
        silent (bool, optional): Won't print to console. Defaults to True.
        include_undef_type (bool, optional): Will include apps with an undefined type. Defaults to False.

    Returns:
        list[SteamApp]: List of SteamApp objects.
    """

    if not STEAM_CLIENT.logged_on and login(anon) != EResult.OK:
        return
    
    # newline
    if not silent: print()

    # Prepping target types
    ttargetTypes:list[str | None] = []
    targetting_types:bool = len(targetTypes) > 0
    if targetting_types:
        ttargetTypes = list( map(lambda ttype: ttype.lower(), targetTypes) )
        if include_undef_type: 
            ttargetTypes.extend([None, ''])
    
    # Getting product info from Steam
    print(f"Requesting product info for {len(appIds)} apps...")
    prod_info = STEAM_CLIENT.get_product_info(appIds, [], metaDataOnly, timeout=120)

    # Building SteamApp objects
    apps:list[SteamApp] = []
    with alive_bar(len(appIds), title='Processing apps' if not silent else '') as bar:
        # TODO should this be done in chunks?
        
        for k, v in prod_info.get('apps', {}).items(): 
            # Filtering by app type
            appType = v.get('common', {}).get('type', '')
            if targetting_types and not ( include_undef_type or appType ):
                if not silent: print(f'> {k}[red] - Filtered due to undefined type')
                bar()
                continue
                
            if appType.lower() not in ttargetTypes:
                # if not silent: print(f'> {k}[red] - Filtered as {appType}')
                bar()
                continue
            
            app = parse_product_info({k: v}, silent)
            if app:
                apps.append(app)
            
            bar()
    
    return apps


async def seedDb() -> None:
    """
    Seeds 'steamapps' inside database.
    """
    
    # Getting MongoDB connection
    print('Connecting to MongoDB. . .', end='')
    mongoClient = MongoClient(MONGODB_URI)
    if not mongoClient:
        print('[red]FAILED')
        return
    print('[green]OK')
    
    # Connecting to Steam
    if not STEAM_CLIENT.logged_on and login(True) != EResult.OK:
        return
    
    # Requesting list of Steam App IDs from Web API
    print('\nPulling app ids from Steam...')
    res = requests.get(
        f'https://api.steampowered.com/IStoreService/GetAppList/v1/', 
        params={
            'key': STEAM_API_KEY,
            # 'if_modified_since': 0  # TODO could use this when updating game list
            'include_dlc': False,
            'include_software': False,
            'include_videos': False,
            'include_hardware': False,
            'max_results': 1000
            }
        )
    if not res:
        print(f'[red]Failed to get Steam app ids:\n{res}')
        return
    
    # Stores API return in a test file
    # with open('test.json', 'w') as f:
    #     f.write(json.dumps(res.json(), indent=4))
    # return
    
    appIds = [app['appid'] for app in res.json().get('response', {}).get('apps', [])]
    if not appIds:
        print('[red]Did not receive any apps')
        return
    
    # Loading SteamApps
    # print('Loading Steam Apps...')
    # test = sample(list(get_cdn().licensed_appIds), 10)
    apps = parse_products(
        # test, 
        appIds,
        targetTypes=['Game'],
        metaDataOnly=False, 
        silent=False
    )
    if len(apps) <= 0:
        print("Failed to load SteamApps")
        return
    # print(apps)
    
    # Collecting images + some housecleaning
    apps = await collectAppImageUrls(apps, 10)
    # print(apps)
    
    # Clearing collection
    print('Clearing database. . .', end='')
    db = mongoClient[DB_NAME]
    res = db.steamapps.delete_many({})
    print('[green]OK' if res.acknowledged else '[red]FAILED')
    if not res.acknowledged:
        return
    
    # Populating database
    print('Populating database. . .', end='')    
    
    try:
        res = db.steamapps.insert_many([app.model_dump() for app in apps])

    # TODO track which Exceptions trigger here
    # As far as I know, 'model_dump' can throw an Exception when
    # attempting to serialize non-JSON-serializable objects like Python Enums
    # that are stored as the object instead of a string or int. Other than that,
    # this is just an informative catch-all. 
    except Exception as e:
        print(f"[red]FAILED[/red]\n"
            f"Error occured while populating database: {e}")
        return
    
    print('[green]OK' if res.acknowledged else '[red]FAILED')

    # Indexing
    # these could technically be in ones 'create_indexes' call but
    # the individual displays or a bit more informative
    print('Indexing db.steamapp.appId...', end='')
    res = db.steamapps.create_index("appId")
    print('[green]OK' if res == 'appId_1' else '[red]FAILED')
    
    print('Indexing db.steamapp.totalSize...', end='')
    res = db.steamapps.create_index("totalSize")
    print('[green]OK' if res == 'totalSize_1' else '[red]FAILED')


async def updateDb() -> None:
    """TODO This scans Steam's catalog
    and re-calculates known SteamApp's file sizes while
    adding new ones. It should also update known app's 
    "timeUpdated" field.
    """
    
    print("Updating database")


def download_images(mongoClient:MongoClient, silent:bool=True) -> None:    
    db = mongoClient[DB_NAME]

    # Downloading images
    with db.steamapps.find() as cursor:
        with alive_bar(db.steamapps.count_documents({}), title='Downloading images') as bar:
            for doc in cursor:
                get_box_image(doc['appId'], silent)
                bar()


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ['s', 'seed', 'u', 'update']:
        print(HELP_MSG)
        sys.exit()
    
    # Connecting Steam client
    # NOTE that the client is not logged in yet
    print('Connecting to Steam. . .', end='')
    STEAM_CLIENT = SteamClient()
    if not STEAM_CLIENT:
        print('[red]FAILED')
        sys.exit(1)
    print('[green]OK')
    
    # Logging in
    login(True)
    
    # Seeds database
    if sys.argv[1].lower() in ['s', 'seed']:
        asyncio.run(seedDb())
    else:
        asyncio.run(updateDb())
    
    # TEST - gets app image urls
    # urls = getAppImageUrls(1808500)
    # print(urls)

    # Logging out of Steam client
    if STEAM_CLIENT.logged_on:
        print('\nLogging out...')
        STEAM_CLIENT.logout()
        print('Exiting')
