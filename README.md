# sumc_fta_mobility_hub_project
This repository contains a library and Jupyter notebooks for the SUMC Mobility Hub Site Selection Tool.

### Setting Up
First, add files to the `rawData` folder as follows:
- EPA EJScreen database
  - The Geodatabase labeled National EJScreen Data at the Block Group Level from the [Data Download page](https://www.epa.gov/ejscreen/download-ejscreen-data)
- EPA SmartLocation database
  - The Geodatabase labeled "data for all areas with coverage" from the [SLD page](https://www.epa.gov/smartgrowth/smart-location-mapping#SLD)
- FTA National Transit Database Facility Inventory
  - Download the Facility Inventory sheet linked [here](https://www.transit.dot.gov/ntd/data-product/2023-annual-database-facility-inventory). For different years, change the year in the URL
- National Renewable Energy Lab Alternative Fuels Data Center (NREL AFDC)
  - This data is provided through an API, but a key is required. Please [register for a key on NREL's developer site](https://developer.nrel.gov/) and save it to a file in the `rawData` folder
- TransitLand GTFS Feeds API
  - Obtain a free Interline API key from [their website](https://www.interline.io/transitland/plans-pricing/). You will need to register an account, but the free plam is more than sufficient for this application. Save the key in a file in the `rawData` folder.

Next, setup your Python environment. This project was developed with Python 3.12, so using that version is recommended, on some systems this can be done by replacing `python` with `python3.12`. Use a virtual environment as follows:

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Then, open `mapper.ipynb`, either using an editor like VS Code or DataSpell, or by running `jupyter notebook` and selecting `mapper.ipynb` from the dropdown. Fill out the values in the `CONFIG` dictionary in the second cell with the names of your files and api keys as necessary, you may not need to change all entries. Finally, run all cells of the notebook to obtain all data (which might take a while), and view the maps!

### Contact
Please email [Jonah](mailto:jonah@sharedusemobilitycenter.org) if you need any help!
