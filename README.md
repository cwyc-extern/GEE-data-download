### README – Using the Global BII Export Script

This guide explains, in simple steps, how to use the `gee_export_optimized.py` script to download a global Biodiversity Intactness Index (BII) map that you can upload to an online map.

---

## 1. What this script does

- **Connects to Google Earth Engine (GEE)**
- **Loads the global Biodiversity Intactness Index (BII) dataset** (latest available year)
- **Compresses and shrinks the data** so the file is small enough for upload (aiming below 900 MB)
- **Exports a GeoTIFF file** you can download and then upload to your online map (e.g. web GIS, map portal)

You don’t need to understand how it works inside, just how to run it.

---

## 2. One-time setup

### 2.1. Make sure you have a Google account and GEE access

1. You need a **Google account** (e.g. Gmail).
2. Apply for Google Earth Engine access if you don’t have it yet:
   - Go to the Earth Engine sign-up page (Google “Google Earth Engine sign up”).
   - Follow the instructions and wait for approval.

### 2.2. Make sure Python is installed

1. On macOS, Python 3 is usually installed. To check:
   - Open the **Terminal** app (Spotlight → type “Terminal”).
   - Type:

```bash
python3 --version
```

   - If you see something like `Python 3.x.x`, you are fine.

2. If Python 3 is not installed, install it from `https://www.python.org/` (or via Homebrew if you know how).

### 2.3. Install the Earth Engine Python package

In the **Terminal**, run:

```bash
pip3 install earthengine-api
```

This installs the Google Earth Engine tools for Python.

### 2.4. Using your Google Cloud project (if the script cannot access GEE)

If your organisation has a **Google Cloud project** already registered with Earth Engine (for example **biodiversity-intactness-index**) and you get access or permission errors when running the script, use that project when you run the script.

1. **Open your project in Google Cloud Console**  
   - Go to: [Google Cloud Console](https://console.cloud.google.com/) and sign in.  
   - Select the project **biodiversity-intactness-index** (project number **1028186117800**) from the project dropdown at the top.

2. **Enable the Earth Engine API** (if it is not already enabled)  
   - In the left menu go to **APIs & Services** → **Library**.  
   - Search for **“Google Earth Engine API”**.  
   - Open it and click **Enable** for this project.

3. **Run the script with your project**  
   The script defaults to project **1028186117800** (biodiversity-intactness-index). You can run:

```bash
python3 gee_export_optimized.py
```

   To use a different project, pass `--project` with the project number or project ID:

```bash
python3 gee_export_optimized.py --project 1028186117800
# or
python3 gee_export_optimized.py --project biodiversity-intactness-index
```

---

## 3. Run the script for global BII

### 3.1. Go to the project folder

In the Terminal, go to the folder where the script is saved:

```bash
cd "/Users/"
```

(If your folder is different, adjust the path accordingly.)

### 3.2. First time: Earth Engine login

The first time you use Earth Engine on this computer, the script may ask you to log in.

**Which account to use:** The script is set up to use **@gmail.com**. When the sign-in page opens, make sure you choose that account—especially if you have several Google accounts logged in (the browser often uses the default one otherwise). You can also use a private/incognito window with only that account logged in.

**If the wrong account is used automatically:** Run the script with **`--login`** first. This clears cached credentials and opens the Google sign-in page so you can choose the right account in the browser. After signing in, run the script again without `--login` to perform the export.

```bash
# Force the login page so you can select the right account (e.g. geoprocessing.cwyc@gmail.com)
python3 gee_export_optimized.py --login
# Then run the export as usual
python3 gee_export_optimized.py --project biodiversity-intactness-index
```

Run (use `--project` if you have a GCP project registered with GEE; see section 2.4):

```bash
python3 gee_export_optimized.py
# Or with your project:
# python3 gee_export_optimized.py --project biodiversity-intactness-index
# To use a different Google account:
# python3 gee_export_optimized.py --expected-account your.email@gmail.com
# To force the login page and choose the right account (clears cached credentials):
# python3 gee_export_optimized.py --login
```

- A link (URL) may appear in the Terminal.
- Click or copy this link into your web browser.
- **Sign in with @gmail.com** (or the account you set with `--expected-account`) and grant access.
- You will receive an **authorization code**.
- Copy that code back into the Terminal when asked.
- After this, Earth Engine will be set up for this computer.

---

## 4. Choosing resolution (detail vs file size)

The script exports a **global** raster (worldwide). File size depends on the **resolution**:

- **100 m** (default): Most detailed, largest file (may be too big for 900 MB).
- **500 m**: Less detailed, smaller file.
- **1000 m (1 km)**: Coarser, but much smaller and more likely below 900 MB.

If you want to change the resolution, you add `--scale`:

```bash
# Recommended if you are worried about size (smaller file)
python3 gee_export_optimized.py --scale 1000

# More detail but larger file
python3 gee_export_optimized.py --scale 500
```

If you just run:

```bash
python3 gee_export_optimized.py
```

it will use **100 m** by default.

**Data format (values in the export):** By default the script keeps the **original 0–1 float** values (highest precision). If compression already keeps your file under the 900 MB limit, you don’t need to change this. To export as 0–100 integers (smaller file), add:

```bash
python3 gee_export_optimized.py --data-format uint8
```

You can combine options: e.g. `--scale 500 --data-format uint8` for 500 m resolution and integer values.

---

## 5. What you will see when it runs

When you run the script, it will:

1. **Show an estimate** of how big the global file might be.
2. **Check global coverage** (after you confirm): the script verifies that the export region and image cover the globe (approx. -180°, -85° to 180°, 85°) before starting the export. If the check fails, the export is not started; use `--skip-global-check` only if you intend a non-global export.
3. Ask you:

   > Do you want to start the Earth Engine export now? [y/N]:

4. Type:
   - `y` and press **Enter** to **start the export**, or
   - `n` and press **Enter** to **cancel**.

The script will **never start downloading/exporting data unless you answer “y”**.

---

## 6. Where to find the exported file

By default, the script sends the output to your **Google Drive** in a folder called `GEE_exports`.

1. Go to `https://drive.google.com/` and log in with the same Google account.
2. Look for a folder named **`GEE_exports`**.
3. Inside, you should see a file with a name like:

   - `gee_export_1000m_orig.tif` (default: 0–1 float), or
   - `gee_export_500m_uint8.tif` (if you used `--data-format uint8` and `--scale 500`), etc.

4. **Download** the file(s) to your computer.

**If you have multiple .tif files (tiles)** from one export, download the **GEE_exports** folder from Google Drive to your computer, then merge the tiles into a single file. Use the **local path** to that folder (the script cannot access Google Drive directly). The `mosaic_geotiff_tiles.py` script now uses GDAL to build a VRT and then creates a compressed, tiled Cloud Optimized GeoTIFF (COG). This is what gave you a ~300 MB global 100 m BII raster in under 10 minutes.

```bash
pip install rasterio tqdm
# GDAL with command-line tools (gdalbuildvrt, gdal_translate), e.g.:
# conda install -c conda-forge gdal

python mosaic_geotiff_tiles.py /path/to/GEE_exports /path/to/output/bii_100m_cog.tif
```

Example: if you downloaded GEE_exports to your Downloads folder:

```bash
python mosaic_geotiff_tiles.py ~/Downloads/GEE_exports ~/Downloads/bii_100m_cog.tif
```

The script will:

- Build a **VRT** over all matching tiles using `gdalbuildvrt`.
- Run `gdal_translate` to create a **Cloud Optimized GeoTIFF (COG)** with:
  - Lossless DEFLATE compression.
  - Internal tiling (good for fast subset reads and different zoom levels).
  - A controlled GDAL cache size (`--gdal-cachemax`, default 512 MB).

Use **`--match`** to mosaic only files whose name contains a given string (e.g. only 100 m or only 500 m tiles):

```bash
python mosaic_geotiff_tiles.py ~/Downloads/GEE_exports ~/Downloads/bii_100m_cog.tif --match 100m
python mosaic_geotiff_tiles.py ~/Downloads/GEE_exports ~/Downloads/bii_500m_cog.tif --match 500m
```

If you need a lighter global file (e.g. close to 300 MB instead of several GB), you can optionally **downsample to ~500 m** by adding `--downsample-500m`:

```bash
python mosaic_geotiff_tiles.py ~/Downloads/GEE_exports ~/Downloads/bii_500m_cog.tif --match 100m --downsample-500m
```

If the mosaic extent is wrong (e.g. only a thin strip at the date line instead of global), force the output extent with **`--bounds`**:

```bash
python mosaic_geotiff_tiles.py GEE_exports ./bii_global_cog.tif --bounds -180,-85,180,85
```

Then use the single output `.tif` (COG) for upload. The export script also has options like `--longitude-bands` to export the globe in bands if a single global export from GEE still causes thin strips; in all cases, you can use `mosaic_geotiff_tiles.py` to merge the tiles into one optimized file.

---

## 7. Uploading to your online map

Once you have the `.tif` file:

1. Go to your online mapping platform (e.g. your web GIS or map portal).
2. Use its **“Upload data”** or **“Add layer”** function.
3. Select the downloaded `.tif` file.
4. Wait for it to upload and process.
5. You should now see the **global BII layer** on your map.

If the platform complains the file is too large, try re-running the script with a **larger scale** (for example, `--scale 1000` instead of 500 or 100).

**If the export is a thin strip (e.g. X: 24 pixels instead of global):** run the script with **`--longitude-bands 6`**. This exports the globe in 6 longitude bands; download all 6 .tif files, then run `mosaic_geotiff_tiles.py` on the folder to merge them into one global raster.

---

## 8. Reusing the script for other datasets

You can also use this script for other Google Earth Engine raster datasets:

- You would change the **asset ID** and possibly the **band name**.
- This requires knowing the correct asset ID and band, so a more technical person might need to help with that part.
- The rest of the steps (run, confirm, download from Google Drive, upload to your map) stay the same.

