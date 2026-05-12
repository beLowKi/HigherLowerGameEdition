const mongoose = require('mongoose');

const steamAppSchema = new mongoose.Schema({
    appId: { 
        type: Number, 
        min: 0, 
        required: true, 
        index: true 
    },
    appType: {
        type: String,
        required: true
    },
    baselanguage: {
        type: String,
        required: true
    },
    names: { 
        type: Map,
        of: String,
        required: true, 
    },
    images: {
        type: Map,
        of: String,
    },
    totalSize: { 
        type: Number, 
        required: true,
        min: 0,
        index: true
    },
    downloadSize: { 
        type: Number, 
        required: true,
        min: 0
    },
    dlcSize: { 
        type: Number, 
        required: true,
        min: 0
    },
    dlcDownloadSize: { 
        type: Number, 
        required: true,
        min: 0
    },    
    timeUpdated: { type: Number, required: false }
});

const SteamApp = mongoose.model('steamapps', steamAppSchema);
module.exports = SteamApp;
