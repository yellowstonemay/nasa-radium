window.RADIUM_GRID_MOON = {
  "grid": {
    "width": 720,
    "height": 360
  },
  "layers": {
    "elevationM": {
      "file": "assets/grids/moon-elev.png",
      "min": -6589.676,
      "max": 7061.875
    },
    "slopeDeg": {
      "file": "assets/grids/moon-slope.png",
      "min": 0.0,
      "max": 40.0
    },
    "roughnessM": {
      "file": "assets/grids/moon-rough.png",
      "min": 0.0,
      "max": 3.093
    },
    "tempDayC": {
      "file": "assets/grids/moon-tempday.png",
      "min": -235.0,
      "max": 130.0,
      "model": "isotonic latitude fit (monotone in |lat|) on published site temperatures",
      "rmseK": 8.1
    },
    "tempNightC": {
      "file": "assets/grids/moon-tempnight.png",
      "min": -235.0,
      "max": 130.0,
      "model": "isotonic latitude fit (monotone in |lat|) on published site temperatures",
      "rmseK": 11.8
    }
  },
  "provenance": {
    "terrain": "LOLA LDEM_4 (Moon) / MOLA MEGDR 16 ppd (Mars), both PDS; slope+relief computed here",
    "temperature": "Moon: Diviner 32 ppd colour raster calibration \u00b7 Mars: regression, modelled"
  }
};
