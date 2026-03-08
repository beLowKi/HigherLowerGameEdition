// const http = require('http')
const fs = require('fs');
const path = require('path');

const mongoose = require('mongoose');
const Model = require('../models/steam_app');


evalStringBool = function(string) {
    if (!string) return false;
    
    if (string.toLowerCase() == 'true') {
        return true;
    } 
    if (string.toLowerCase() == 'false') {
        return false;
    }
    return string == true;
};


// GET: /apps - returns list of all SteamApps
const getApps = async(req, res, next) => {
    const q = await Model.find({}).exec();
    if (!q) {
        return res
            .status(500)
            .json('Could not pull apps from database');
    }
    
    return res
        .status(200)
        .json(q);
};


// POST: /apps - returns SteamApps query results
// request body can inlcude 'query', 'projection', and/or 'options' as nested maps.
const queryApps = async(req, res, next) => {
    const query = req.body.query || {};
    const projection = req.body.projection || {};
    const options = req.body.options || {};
    // console.log(`Querying steam-apps: query=${query} projection=${projection} options=${options}`);
    
    let q = null;
    try {
        q = await Model.find(query, projection, options).exec();
    } catch (err) {
        return res
            .status((err instanceof mongoose.MongooseError || err instanceof mongoose.mongo.MongoServerError) ? 400 : 500)
            .json(err);
    }

    return res
        .status(200)
        .json(q);
};


// GET: /apps/:appid - returns app_info for one Steam app
const getApp = async(req, res, next) => {
    if (!req.params.appid) {
        // console.log('woohoo');
        return res
            .status(400)
            .json({message: "Missing appid"});
    }

    console.log(`Pulling app info for App ID ${req.params.appid}`);

    // Querying database
    const q = await Model.findOne({ appId: req.params.appid }).exec();
    if (!q) {
        return res
            .status(404)
            .json({message: "Did not find matching app"})
    }
    
    return res
        .status(200)
        .json(q)
};


// GET: /app/:appid/boximage - returns 600x900 box image of game
const getAppImage = (req, res) => {
    if (!req.params.appid) {
        return res
            .status(400)
            .json({message: "Missing appid"});
    }

    console.log(`Sending 600x900 box image for ${req.params.appid}`);
    
    const imgPath = path.join(process.cwd(), 'public', 'images', req.params.appid + '.jpg');
    console.log(`Checking at ${imgPath}`);

    if (!fs.existsSync(imgPath)) {
        return res
            .status(404)
            .json('No known box image for the given app id');
    }
        
    res.sendFile(imgPath);
}


module.exports = {
    getApps,
    queryApps,
    getApp,
    getAppImage
}