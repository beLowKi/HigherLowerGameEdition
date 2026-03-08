const mongoose = require('mongoose');

const steamAppSchema = new mongoose.Schema({
    appId: { 
        type: Number, 
        min: 0, 
        required: true, 
        index: true 
    },
    names: { 
        type: Map,
        of: String,
        required: true, 
    },
    totalSize: { 
        type: Number, 
        required: true,
        min: 0
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

const SteamApp = mongoose.model('steamApps', steamAppSchema);
module.exports = SteamApp;
