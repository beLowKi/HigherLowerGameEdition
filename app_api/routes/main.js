const express = require('express');
const router = express.Router();

const appsController = require('../controllers/steam_app');

// Defining routes
router.get('/apps', appsController.getApps);
router.post('/apps', appsController.queryApps);
router.get('/apps/:appid', appsController.getApp);
router.get('/apps/images/:appid', appsController.getAppImage);

module.exports = router;