import sys
import os
import io
import json

import urllib.request
from PIL import Image
# import urllib.response

import requests
from bs4 import BeautifulSoup

# from random import sample
from alive_progress import alive_bar

from pymongo import MongoClient
from pydantic import BaseModel, Field
# from pydantic.dataclasses import dataclass

from rich import print
from rich.pretty import pprint

import steam
from steam.client import SteamClient
from steam.client.cdn import CDNClient
from steam.enums.common import EResult


# MongoDB config
MONGO_HOST = os.getenv('DB_HOST') or '127.0.0.1'
MONGODB_URI = f'mongodb://{MONGO_HOST}'
DB_NAME = 'higherlower-game'

# Used in non-anon login
STEAM_USERNAME = 'Ghouligo'
STEAM_PASSWORD = 'E6av^93ay8Zr'
STEAM_API_KEY = '22E35A3B4C0A81F721119F0004D57DF5'

# Manifests with these in their name are ignored when calculating file size.
DEPOT_MANIFEST_BLACKLIST:set[str] = {'beta', 'alpha', 'test'}

print('Connecting to Steam. . .', end='')
STEAM_CLIENT = SteamClient()
if not STEAM_CLIENT:
    print('[red]FAILED')
    sys.exit(1)
print('[green]OK')


# Models
# class LibraryAsset(BaseModel):
#     image: dict[str, str]           = Field(default={})
#     image2x: dict[str, str]         = Field(default={})
#     # logo_position: dict[str, str]   = Field(default={})


# class LibraryAssets(BaseModel):
#     library_capsule: LibraryAsset   = Field(default_factory=LibraryAsset)
#     library_hero: LibraryAsset      = Field(default_factory=LibraryAsset)
#     library_hero_blur: LibraryAsset = Field(default_factory=LibraryAsset)
#     library_logo: LibraryAsset      = Field(default_factory=LibraryAsset)
#     library_header: LibraryAsset    = Field(default_factory=LibraryAsset)


class SteamApp(BaseModel):
    appId: int
    appType: str = ''
    names: dict[str, str] = Field(default_factory={})
    
    icon: str = ''
    # lib_assets: LibraryAssets = Field(default_factory=LibraryAssets)
    # version: str = ''
    baselanguage: str = ''
    
    # Assumes Windows, English, and no DLC
    totalSize: int = 0
    downloadSize: int = 0

    # Bonus
    dlcSize: int = 0
    dlcDownloadSize: int = 0
    
    timeUpdated: int = -1


def login(anon:bool=False) -> EResult:
    # enum CMsgClientLogonResponse.eresult
    # https://github.com/ValvePython/steam/blob/513c68ca081dc9409df932ad86c66100164380a6/protobufs/steammessages_clientserver.proto#L95-L118
    print('Logging in. . .', end='\n' if not anon else '')
    if not anon:
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
    # source: https://gaming.stackexchange.com/questions/359614/is-there-a-way-to-download-the-box-art-for-steam-games#:~:text=Other%20Art%20Formats:%20Beyond%20the%20main%20box,using%20URLs%20like:%20https://steamcdn-a.akamaihd.net/steam/apps/255220/header.jpg%2C%20https://steamcdn-a.akamaihd.net/steam/apps/255220/logo.png%2C%20and%20https://steamcdn-a.akamaihd.net/steam/apps/255220/library_hero.jpg.
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


def get_packages(appId:int) -> set[int]:
    res = requests.get('https://store.steampowered.com/app/{appId}'.format(appId=appId))
    if not res:
        print(f'[red]Failed to get webpage: {res}')
        return []

    soup = BeautifulSoup(res.content, 'html.parser')
    if not soup:
        print(f'[red]Failed to create soup')
        return []
    
    packages:set[int] = set()
    for tag in soup.find_all('form', action='https://store.steampowered.com/cart/', method='POST'):
        if 'add_to_cart' not in tag['name']:
            continue
        
        hidden = tag.find(lambda t2: t2['name'] == 'subid')
        if not hidden:
            print('Could not find hidden input tag with sub id')
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
    
    if not silent: print('\t-> Checking depot info')
    
    for k, v in prod_info.get('depots', {}).items():
        # Depots are keyed with their depot id
        if not k.isdigit(): 
            print(f'\t\t{k}[yellow] - Non digit key')
            continue

        # They also have 'manifests' which are lists of the files inside them
        if 'manifests' not in v: 
            print(f'\t\t{k}[yellow] - Missing manifests')
            continue
        
        # Config filters
        if 'config' in v:
            # Skipping non-Windows
            oslist = v['config'].get('oslist')
            if oslist and 'windows' not in oslist:
                print(f'\t\t{k}[yellow] - Non-windows')
                continue
            
            # Skipping defined, non-baselanguage
            lang = v['config'].get('language', '')
            if lang and lang not in baselanguage:
                print(f'\t\t{k}[yellow] - Non-{baselanguage.capitalize()} language: {lang}')
                continue
        
        # Summing manifests sizes
        print(f'\t\t{k} - Reading manifests')
        for man_id, info, in v['manifests'].items():
            # Skipping blacklisted manifest ids
            blacklist_trigger:str = ''
            for token in DEPOT_MANIFEST_BLACKLIST:
                if token.lower() in man_id.lower(): 
                    blacklist_trigger = token
                    break
            
            if blacklist_trigger != '':
                print(f'\t\t\t{man_id}[red] - Blacklisted by token \'{blacklist_trigger}\'')
                continue
            
            if any([token.lower() in man_id for token in DEPOT_MANIFEST_BLACKLIST]):
                print(f'\t\t\t{man_id}[yellow] - Skipped as blacklisted')
                continue
            
            # Adding DLC
            if 'dlcappid' in v:
                print(f'\t\t\t{man_id}[green] - Added to dlcSize')
                dlcSize +=             int( info.get('size', 0) )
                dlcDownloadSize +=    int( info.get('download', 0) )
            
            # Regular depots
            else:
                print(f'\t\t\t{man_id}[green]- Added to file size')
                totalSize +=           int( info['size'] )
                downloadSize +=        int( info['download'] )
        
    return totalSize, downloadSize, dlcSize, dlcDownloadSize


def parse_product_info(app_pck: dict, silent:bool = True) -> SteamApp:
    """Creates a SteamApp from an app_info dictionary returned from SteamClient.get_product_info.

    Args:
        app_pck (dict): {appId: app_info} dictionary returned from SteamClient.get_product_info.
        silent (bool, optional): Won't print to console. Defaults to True.
    """
    
    # First key should be an app id
    if not (len(app_pck.keys()) == 1 and isinstance(list(app_pck.keys())[0], int)):
        if not silent: print(f'\t[red]Invalid keys; must be only 1 appId')
        return
    
    # Should only be 1 value: a dict
    if not ( len(app_pck.values()) == 1 and isinstance(list(app_pck.values())[0], dict) ):
        if not silent: print('\t[red]Invalid value; must be 1 dict of app info')
        return
    
    # Splitting data
    appId = list(app_pck.keys())[0]
    if not silent: print(f'> {appId}')

    prod_info = list(app_pck.values())[0]
    
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
        print('\t[red] - Missing \'depots\' entry')
        # print(prod_info.keys())
    
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
            print(f'\t[green] - Found names {names}')
        else:
            print(f'\t[red] - Failed to find names')
    
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
        if not silent: print(f'\t[red]Unhandled Exception: {e}')
        return
    
    return app


def parse_products(
        app_ids: list[int],
        target_types: list[str] = [],
        meta_data_only:bool=False, 
        silent:bool = True,
        include_undef_type:bool = False,
        anon:bool=False
) -> list[SteamApp]:
    """Parses SteamApp objects from a list of app ids.

    Args:
        app_ids (list[int]): Steam app ids
        target_types (list[str], optional): Filters apps outside these types when set. Defaults to [].
        meta_data_only (bool, optional): Will only return metadata. Defaults to False.
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
    ttarget_types:list[str | None] = []
    targetting_types:bool = len(target_types) > 0
    if targetting_types:
        ttarget_types = list( map(lambda ttype: ttype.lower(), target_types) )
        if include_undef_type: 
            ttarget_types.extend([None, ''])
        
    apps:list[SteamApp] = []
    with alive_bar(len(app_ids), title='Processing apps' if not silent else '') as bar:
        # TODO should this be done in chunks?
        prod_info = STEAM_CLIENT.get_product_info(app_ids, [], meta_data_only, timeout=120)
        
        for k, v in prod_info.get('apps', {}).items():
            
            # Filtering by app type
            appType = v.get('common', {}).get('type', '')
            if targetting_types and not ( include_undef_type or appType ):
                if not silent: print(f'> {k}[red] - Filtered due to undefined type')
                bar()
                continue
                
            if appType.lower() not in ttarget_types:
                if not silent: print(f'> {k}[red] - Filtered as {appType}')
                bar()
                continue
            
            apps.append(parse_product_info({k: v}, silent))
            bar()
    
    return apps


def seed_db() -> None:
    """
    Seeds 'steam_apps' inside database.
    """
    
    # Getting MongoDB connection
    print('Connecting to MongoDB. . .', end='')
    mongo_client = MongoClient(MONGODB_URI)
    if not mongo_client:
        print('[red]FAILED')
        return
    print('[green]OK')
    
    # Connecting to Steam
    if not STEAM_CLIENT.logged_on and login(True) != EResult.OK:
        return
    
    # Requesting list of Steam App IDs from Web API
    print('\nPulling app ids from Steam. . .')
    res = requests.get(
        f'https://api.steampowered.com/IStoreService/GetAppList/v1/', 
        params={
            'key': STEAM_API_KEY,
            # 'if_modified_since': 0  # TODO could use this when updating game list
            'include_dlc': False,
            'include_software': False,
            'include_videos': False,
            'include_hardware': False,
            'max_results': 10000
            }
        )
    if not res:
        print(f'[red]Failed to get Steam app ids')
        return
    
    # with open('test.json', 'w') as f:
    #     f.write(json.dumps(res.json(), indent=4))
    # return
    
    app_ids = [app['appid'] for app in res.json().get('response', {}).get('apps', [])]
    if not app_ids:
        print('[red]Did not receive any apps')
        return
    
    # Clearing collection
    print('Clearing database')
    db = mongo_client[DB_NAME]
    res = db.steam_apps.delete_many({})
    
    # Loading SteamApps
    print('Loading Steam Apps...')
    # test = sample(list(get_cdn().licensed_app_ids), 10)
    apps = parse_products(
        # test, 
        app_ids,
        target_types=['Game'],
        meta_data_only=False, 
        silent=True
    )

    # Some housecleaning
    for app in apps:
        # Defaults to english
        # NOTE that this usually means the baselanguage on Steam is empty or missing
        if not app.baselanguage:
            app.baselanguage = 'english'

    # Populating database
    print('\nPopulating database. . .', end='')
    res = db.steamapps.insert_many([app.model_dump() for app in apps])
    print('[green]OK' if res.acknowledged else '[red]FAILED')

    # Downloading images
    with alive_bar(len(apps), title='Downloading images') as bar:
        for app in apps:
            get_box_image(app.appId)
            bar()
    
    print('Closing connection')
    mongo_client.close()
    print('Connection closed')


def update_db() -> None:
    pass


def download_images(silent:bool=True) -> None:    
    # Getting MongoDB connection
    print('Connecting to MongoDB. . .', end='')
    mongo_client = MongoClient(MONGODB_URI)
    if not mongo_client:
        print('[red]FAILED')
        return
    print('[green]OK')
    
    db = mongo_client[DB_NAME]

    # Downloading images
    with db.steamapps.find() as cursor:
        with alive_bar(db.steamapps.count_documents({}), title='Downloading images') as bar:
            for doc in cursor:
                get_box_image(doc['appId'], silent)
                bar()


if __name__ == '__main__':
    # seed_db()
    # download_images()
    # print(len(os.listdir(r'E:\Coding\Web Dev\higherlower_games\public\images')))
    
        
    # test_id = 1030300
    # pprint(parse_products([test_id], ['Game'], meta_data_only=False, silent=False, anon=True))
    
    # login(True)
    # STEAM_CLIENT.anonymous_login()
    # pprint(STEAM_CLIENT.get_product_info([test_id], []))
    
    if STEAM_CLIENT.logged_on:
        print('\nLogging out...')
        STEAM_CLIENT.logout()
        print('Exiting')
