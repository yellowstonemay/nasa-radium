window.RADIUM_GRID_MARS = {
  "grid": {
    "width": 720,
    "height": 360
  },
  "layers": {
    "elevationM": {
      "file": "assets/grids/mars-elev.png",
      "min": -6803.657,
      "max": 8574.657
    },
    "slopeDeg": {
      "file": "assets/grids/mars-slope.png",
      "min": 0.0,
      "max": 40.0
    },
    "roughnessM": {
      "file": "assets/grids/mars-rough.png",
      "min": 0.0,
      "max": 2.601
    },
    "tempDayC": {
      "file": "assets/grids/mars-tempday.png",
      "min": -160.0,
      "max": 30.0,
      "model": "latitude + elevation regression on published sites",
      "rmseK": 5.1
    },
    "tempNightC": {
      "file": "assets/grids/mars-tempnight.png",
      "min": -160.0,
      "max": 30.0,
      "model": "latitude + elevation regression on published sites",
      "rmseK": 3.7
    }
  },
  "provenance": {
    "terrain": "LOLA LDEM_4 (Moon) / MOLA MEGDR 16 ppd (Mars), both PDS; slope+relief computed here",
    "temperature": "Moon: Diviner 32 ppd colour raster calibration \u00b7 Mars: regression, modelled"
  }
};
