// const http = require('http')
const fs = require('fs');
const path = require('path');

const mongoose = require('mongoose');
const Model = require('../models/steam_app');


// Evaluates a string boolean like "true" or "false"
evalStringBool = function(string) {
    if (!(string && typeof string === "string")) {
        return false;
    }

    if (string.toLowerCase() === 'true') {
        return true;
    }

    if (string.toLowerCase() === 'false') {
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
            .status(
                // Mongoose or Mongo errors are assumed to be caused by user error (400).
                // Anything else is assumed to be server error (500).
                (err instanceof mongoose.MongooseError || err instanceof mongoose.mongo.MongoServerError) 
                    ? 400 
                    : 500
            )
            .json(err);
    }

    return res
        .status(200)
        .json(q);
};


/*
POST: /apps-sample - samples a number of SteamApps.
Random apps within the criteria are selected, so the same requests
with the same body may receive different apps.

Request body parameters:
    match: document     - Query that filters sampled SteamApp
    limit: int = 10      - Number of SteamApps returned     
*/
const sampleApps = async(req, res, next) => {
    // Parsing request
    const match = req.body.match || {};
    const limit = req.body.limit || 10; 
    
    // Performing query
    let q = null;
    try {
        q = await Model.aggregate([
            { $match: match },
            
            /*
                Some StackOverflow posts from a few years ago
                claim that $sample aggregation stage can have duplicates
                (multiple selection of same _id doc). I couldn't verify this
                on MongoDB's official website, but if it's true then a solution
                would be a stage grouping documents by _id post-sample like
                the following code.
                
                Source: https://stackoverflow.com/questions/59753520/aggregation-using-sample#:~:text=Comments,-Add%20a%20comment&text=This%20matches%20a%20random%20selection,give%20you%20the%20same%20output.
            */
            { $sample: { size: Math.round(limit * 2.5) } },
            {
                $group: {
                    _id: "$_id",
                    doc: { "$first": "$$ROOT" }
                }
            },
            
            // Sets inner 'doc' of each group as root document
            { $replaceWith: "$doc" },
            
            { $limit: limit }
        ]);
    } catch (err) {
        return res
            .status(
                // Mongoose or Mongo errors are assumed to be caused by user error (400).
                // Anything else is assumed to be server error (500).
                (err instanceof mongoose.MongooseError || err instanceof mongoose.mongo.MongoServerError) 
                    ? 400 
                    : 500
            )
            .json(err);
    }

    return res
        .status(200)
        .json(q);
}


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
// depreciated - application is switching to requesting from Steam's CDN directly
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
    sampleApps,
    getApp,
    getAppImage
}