window.RADIUM_PROSPECT_META = {
  "file": "assets/grids/earth-prospect.png",
  "width": 1440,
  "height": 1440,
  "bounds": [
    [
      -85.0511287798,
      -180
    ],
    [
      85.0511287798,
      180
    ]
  ],
  "projection": "Web Mercator, square",
  "screenedCells": 224663,
  "threshold": 65,
  "envelope": {
    "tempMeanC": {
      "median": 12.198,
      "spread": 14.902,
      "min": -28.338,
      "max": 28.952,
      "weight": 2.2
    },
    "tempMaxC": {
      "median": 28.008,
      "spread": 16.337,
      "min": -12.92,
      "max": 42.612,
      "weight": 1.1
    },
    "tempMinC": {
      "median": -5.482,
      "spread": 15.49,
      "min": -41.805,
      "max": 20.922,
      "weight": 1.1
    },
    "precipMmDay": {
      "median": 0.475,
      "spread": 0.464,
      "min": 0.001,
      "max": 5.063,
      "weight": 1.8
    },
    "precipSeasonality": {
      "median": 50.027,
      "spread": 30.961,
      "min": 9.869,
      "max": 174.357,
      "weight": 0.7
    },
    "elev": {
      "median": 716.095,
      "spread": 879.417,
      "min": -115.361,
      "max": 5374.714,
      "weight": 0.5
    },
    "slope": {
      "median": 0.801,
      "spread": 1.978,
      "min": 0.006,
      "max": 7.344,
      "weight": 0.7
    },
    "relief": {
      "median": 89.913,
      "spread": 151.783,
      "min": 0.682,
      "max": 990.034,
      "weight": 0.5
    }
  },
  "datasets": [
    {
      "name": "AWS Terrain Tiles (Mapzen terrarium)",
      "detail": "SRTM / NED / GMTED / ETOPO blend, 0.25 degree means at zoom 5",
      "url": "https://registry.opendata.aws/terrain-tiles/"
    },
    {
      "name": "WorldClim 2.1 bio, 10 arc-minute",
      "detail": "mean/max/min temperature, precipitation and seasonality, 1970-2000",
      "url": "https://www.worldclim.org/data/worldclim21.html"
    },
    {
      "name": "Natural Earth 50m land, countries, 10m populated places",
      "detail": "land mask, country labels, nearest settlement",
      "url": "https://www.naturalearthdata.com/"
    },
    {
      "name": "NASA POWER climatology 2001-2020",
      "detail": "finalist refinement: temperature, pressure, wind, humidity, rain, solar",
      "url": "https://power.larc.nasa.gov/"
    },
    {
      "name": "NOAA ETOPO1",
      "detail": "finalist refinement: 1 arc-minute elevation and local slope",
      "url": "https://www.ngdc.noaa.gov/mgg/global/"
    }
  ]
};
