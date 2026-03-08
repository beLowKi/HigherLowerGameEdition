# HIGHER-LOWER: GAME EDITION

I made "Higher or Lower" for video game file sizes using the MEAN stack. The main parts are an Express API for pulling SteamApp-related stuff from a database and an single-page application (SPA) frontend made with Angular. It's my second time working with the MEAN stack and one of very few web apps I've made; just thought it'd be fun.

## API endpoints

- GET: /api/apps - returns a list of SteamApps
- POST: /api/apps - returns a list of SteamApps resulting from a query
    - Request body can include "query", "projection", and "options" as JSON maps for the Mongo.find call
- GET: /api/apps/:appid - returns SteamApp of matching appid (TODO/FIXME some steam apps share an id? so this should return a list instead of just one)
- GET: /api/apps/image/:appid - returns a display image for the SteamApp matching appid

## Getting game sizes

### Steam

I used a mix of Steam's Web API, their [site](https://steamcdn-a.akamaihd.net) for hosting files, and a python library called ["steam"](https://steam.readthedocs.io/en/stable/). Each SteamApp object is parsed from the results of SteamClient.get_product_info which includes the info you'd see on [SteamDB](https://steamdb.info) --summing depot manifest sizes to roughly get the game's total file size. I filter which depots are included in the calculation similar to how SteamDB does which is just filtering out the ones that aren't Windows or the game's base language which is usually English.

Technically, it would be better to use all the depot ids listed in package info--another return in SteamClient.get_product_info, but I'd already implemented the first method before I found a way to do that. You can scrape an app's store page for package ids, and I did create a method to do that, I just haven't implemented it yet.

### Itch.io

Not implemented

## TODO/Possible improvements

- the /api before each endpoint is an unecessary leftover from when the app had an Express landing page and can be removed.
- endpoint for images relies on static files I downloaded via a script, but they're probably not needed. I'll still probably have a dedicated endpoint for it just so a controller can handle when apps may or may not have a box image, header, and so on.


## References

site with static files: <https://steam.readthedocs.io/en/stable/>

python-steam: <https://steam.readthedocs.io/en/stable/>

steamdb: <https://steamdb.info>
