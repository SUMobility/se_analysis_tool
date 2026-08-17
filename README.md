# Safety and Economic Analysis Mapping Tool
This repository contains a library and Jupyter notebooks for the SUMC Safety and Economic Analysis mapping tool.

### Setting Up
First, add files to the `rawData` folder as follows:
- EPA EJScreen database
  - The Geodatabase labeled National EJScreen Data at the Block Group Level from the [Data Download page](https://www.epa.gov/ejscreen/download-ejscreen-data)
- EPA SmartLocation database
  - The Geodatabase labeled "ESRI Geodatabase" from the [SLT page](https://www.epa.gov/smartgrowth/smart-location-mapping#Trans45)
- FTA National Transit Database Facility Inventory
  - Download the Facility Inventory sheet linked [here](https://www.transit.dot.gov/ntd/data-product/2023-annual-database-facility-inventory). For different years, change the year in the URL
- National Laboratory of the Rockies (NLR AFDC)
  - This data is provided through an API, but a key is required. Please [register for a key on NLR's developer site](https://developer.nlr.gov/) and save it to a file in the `rawData` folder
- TransitLand GTFS Feeds API
  - Obtain a free Interline API key from [their website](https://www.interline.io/transitland/plans-pricing/). You will need to register an account, but the free plan is more than sufficient for this application. Save the key in a file in the `rawData` folder.
- Census API
  - Obtain a free Census API Key from [their website](https://api.census.gov/data/key_signup.html). Save this key in a separate folder in the `rawData` folder 
- Load Area
  - Obtain a spatial data file containing a single Polygon or Multipolygon corresponding to the area you wish to load, and place it in the `rawData` folder. The file must have EPSG:4326 as the CRS.

Next, setup your Python environment. This project was developed with Python 3.12, so using that version is recommended, on some systems this can be done by replacing `python` with `python3.12`. Use a virtual environment as follows:

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Then, open `mapper.ipynb`, either using an editor like VS Code or DataSpell, or by running `jupyter notebook` and selecting `mapper.ipynb` from the dropdown. Fill out the values in the `CONFIG` dictionary in the second cell with the names of your files and api keys as necessary. Instructions are present for each entry in the notebook. You may not need to change all entries. Finally, run all cells of the notebook to obtain all data (which might take a while), and view the maps. You can view definitions, schemas, and configuration files by referring to readmes in /SEDataObjects and /SEDataObjects/transitWrappers.

### Contact
Please email [Colin](mailto:colin@sharedusemobilitycenter.org) if you need any help!
