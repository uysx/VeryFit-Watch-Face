import os
import re
import json
import logging
from pathlib import Path

import requests


# ============================================================
# CONFIG
# ============================================================

DIAL_API_URL = "https://device.idoocloud.com/api/device/facestore/free/get"
DETAIL_API_URL = "https://device.idoocloud.com/api/device/face/v4/get"

APP_KEY = "548a50bc9f0a45d0bdfcdb5d194641d8"
AUTH_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJkYXRldGltZSI6MTc4NzI0ODM2OTg5NywidXNlcl90eXBlIjoiVVNFUiIsInVzZXJfaWQiOiI1NzMwNTEwMzE4NzM3ODU4NTYiLCJzb3VyY2UiOiJhcHAiLCJ0eXBlIjoiYXBwIiwiYXBwX2lkIjoiMTAwMDAiLCJhY2NvdW50IjoiYXJub2xkZnVuZ21hbmNlcGxhdXNrYXNAZ21haWwuY29tIiwiaWF0IjoxNzg3MjQ4MzY5LCJleHAiOjQ5NDA4NDgzNjl9.e70zKmc4o0QOi5IZlfpxyhOJkGRmCJTDdjClGLo2qpFCdHavve8F0HGWx8-xwHz6YJanfnVHJ47m2RwSYdYx5Q"

# Hardware configuration
HW_CONFIG = {
    "deviceId": "512",
    "otaVersion": "1.01.23",
    "appFaceVersion": "6",
    "supportFaceVersion": "6",
}

# Payload configuration
STATIC_PAYLOAD = {
    "age": 14,
    "bmi": "19.5",
    "deviceInfoList": [],
    "deviceToken": "c9ZbLleezEwtnKWZ4Qmzwj:APA91bG3U6SBxQz0BJZSANSgaDVUTvbJHJH6LtjwdY17xK3BdtIpJDBJW4ehpivzp6DJ2ruQMw-mVQEG3xi6xFTJMDR2j6eoMR-m8EQ8CH57UMHIDn-ZBS4",
    "height": 168,
    "language": "en",
    "sex": 1,
    "weight": 55,
}

PAGE_SIZE = 500

# Download directory beside this script (Via deviceId numbers)
DOWNLOAD_DIR = Path(__file__).parent / "downloads" / HW_CONFIG["deviceId"]

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "Authorization": AUTH_TOKEN,
    "appKey": APP_KEY,
})


# ============================================================
# HELPERS
# ============================================================

def safe_filename(name):
    """Make a filename safe for Windows."""
    name = str(name or "Unknown")

    name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        name
    )

    name = re.sub(r"\s+", " ", name)

    return name.strip().rstrip(".")


def get_extension_from_url(url):
    """Try to determine the file extension from a download URL."""

    path = url.split("?", 1)[0].split("#", 1)[0]

    extension = os.path.splitext(path)[1]

    if extension and len(extension) <= 10:
        return extension

    return ".zip"


# ============================================================
# GET DIAL LIST
# ============================================================

def get_dials():
    print("\nFetching free dials...")

    params = STATIC_PAYLOAD.copy()
    params.update(HW_CONFIG)

    params.update({
        "pageSize": PAGE_SIZE,
    })

    try:
        response = session.post(
            DIAL_API_URL,
            params=params,
            timeout=15,
        )

        print("LIST STATUS:", response.status_code)

        response.raise_for_status()

        payload = response.json()

        if payload.get("status") != 200:
            print(
                "LIST API ERROR:",
                payload.get("status"),
                payload.get("message")
            )
            return []

        result = payload.get("result")

        if not isinstance(result, dict):
            print("Unexpected result:", type(result))
            return []

        # IMPORTANT:
        # IDO returns the dial records under result.items
        dials = result.get("items", [])

        if not isinstance(dials, list):
            print("Unexpected items:", type(dials))
            return []

        print(
            f"Found {len(dials)} dials "
            f"(server reports {result.get('numRows')})"
        )

        return dials

    except Exception as e:
        logging.error("Error fetching dials: %s", e)

        if "response" in locals():
            logging.error(
                "Server response: %s",
                response.text
            )

        return []


# ============================================================
# GET DIAL DETAIL
# ============================================================

def get_dial_detail(dial):
    dial_id = dial.get("id")
    name = dial.get("name", "Unknown")

    params = STATIC_PAYLOAD.copy()

    # Same hardware merge used by DialDetailWorker
    params.update(HW_CONFIG)

    params.update({
        "id": int(dial_id)
        if str(dial_id).isdigit()
        else dial_id,

        "language": "en",
    })

    try:
        response = session.get(
            DETAIL_API_URL,
            params=params,
            timeout=15,
        )

        print(
            f"DETAIL {dial_id}: "
            f"{response.status_code}"
        )

        if response.status_code != 200:
            print(
                f"  Detail HTTP error: "
                f"{response.text}"
            )
            return None

        data = response.json()

        status = data.get("status")

        if status not in (0, 200, None):
            print(
                f"  Detail API error: "
                f"{status}: {data.get('message')}"
            )
            return None

        result = data.get("result")

        if not isinstance(result, dict):
            print("  Unexpected detail result")
            return None

        return result

    except Exception as e:
        print(
            f"  Detail request failed "
            f"for {name}: {e}"
        )
        return None


# ============================================================
# FIND DOWNLOAD URL
# ============================================================

def find_download_url(detail):
    """
    Find the actual dial package URL.

    The application expects linkUrl, but this also checks
    a few common nested locations so the script can handle
    slightly different API responses.
    """

    if not isinstance(detail, dict):
        return None

    # Primary field used by the application
    url = detail.get("linkUrl")

    if isinstance(url, str) and url.strip():
        return url.strip()

    # Possible alternative fields
    for key in (
        "downloadUrl",
        "fileUrl",
        "packageUrl",
        "url",
    ):
        value = detail.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    # Search one level of nested dictionaries
    for value in detail.values():

        if isinstance(value, dict):
            url = find_download_url(value)

            if url:
                return url

        elif isinstance(value, list):

            for item in value:

                if isinstance(item, dict):
                    url = find_download_url(item)

                    if url:
                        return url

    return None


# ============================================================
# DOWNLOAD FILE
# ============================================================

def download_file(url, dial):
    dial_id = dial.get("id")
    name = dial.get("name", "Unknown")

    safe_name = safe_filename(name)

    extension = get_extension_from_url(url)

    filename = f"{dial_id}_{safe_name}{extension}"

    output_path = DOWNLOAD_DIR / filename

    try:
        print(f"  Downloading: {url}")

        response = session.get(
            url,
            stream=True,
            timeout=30,
        )

        response.raise_for_status()

        if output_path.suffix.lower() == ".json":
            output_path = output_path.with_suffix(".zip")

        with open(output_path, "wb") as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 256
            ):
                if chunk:
                    f.write(chunk)

        size = output_path.stat().st_size

        print(
            f"  SAVED: {output_path.name} "
            f"({size:,} bytes)"
        )

        return output_path

    except Exception as e:

        print(
            f"  DOWNLOAD FAILED: {e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("IDO Dial Downloader")
    print("=" * 70)

    # Create output folder
    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        f"Output folder:\n"
        f"{DOWNLOAD_DIR}"
    )

    # --------------------------------------------------------
    # Get marketplace dials
    # --------------------------------------------------------

    dials = get_dials()

    if not dials:
        print("\nNo dials found.")
        return

    print()

    successful = 0
    failed = 0

    # --------------------------------------------------------
    # Process each dial
    # --------------------------------------------------------

    for index, dial in enumerate(dials, start=1):

        dial_id = dial.get("id")
        name = dial.get("name", "Unknown")

        print()
        print(
            f"[{index}/{len(dials)}] "
            f"{name} "
            f"(ID {dial_id})"
        )

        if not dial_id:
            print("  Missing dial ID")
            failed += 1
            continue

        # ----------------------------------------------------
        # Resolve detail
        # ----------------------------------------------------

        detail = get_dial_detail(dial)

        if not detail:
            print("  Could not resolve dial detail")
            failed += 1
            continue

        # ----------------------------------------------------
        # Find actual package URL
        # ----------------------------------------------------

        link_url = find_download_url(detail)

        if not link_url:
            print("  No linkUrl found.")

            # Save detail so we can inspect unusual responses
            debug_name = (
                f"{dial_id}_"
                f"{safe_filename(name)}_detail.json"
            )

            debug_path = DOWNLOAD_DIR / debug_name

            try:
                with open(
                    debug_path,
                    "w",
                    encoding="utf-8"
                ) as f:
                    json.dump(
                        detail,
                        f,
                        indent=2,
                        ensure_ascii=False
                    )

                print(
                    f"  Detail saved for inspection: "
                    f"{debug_path.name}"
                )

            except Exception:
                pass

            failed += 1
            continue

        print(
            f"  linkUrl: {link_url}"
        )
        
        # Wait a moment before downloading to avoid overwhelming the server
        import time
        time.sleep(1.5)  # Sleep for 1.5 seconds

        # ----------------------------------------------------
        # Download
        # ----------------------------------------------------

        result = download_file(
            link_url,
            dial
        )

        if result:
            successful += 1
        else:
            failed += 1

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)

    print(
        f"Successful: {successful}"
    )

    print(
        f"Failed:     {failed}"
    )

    print(
        f"Output:     {DOWNLOAD_DIR}"
    )


if __name__ == "__main__":
    main()
