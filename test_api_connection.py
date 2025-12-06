"""
API Connection Test Script
Test the TCS iON API endpoint with different configurations
"""

import requests
import json
from urllib.parse import urlencode, quote, unquote

# API Configuration from the image
BASE_URL = "https://www3.tcsion.com/iONBizServices/iONWebService"

# Parameters from the image (URL decoded)
PARAMS = {
    'servicekey': 'WaJkcnPwTLXzm/2FQICFcn3w==',
    's': '4CnZ/2FgPXtzK8efa1RmpmLg==',
    'u': 'TIX8NflllNXow1Ic/ZoBmze/jwyVQjfsnDydzQqFPGDD79kH58CkQVDgHATBFfbrNow'
}

# URL encoded parameters (WORKING VERSION - CONFIRMED)
PARAMS_ENCODED = {
    'servicekey': 'WaJkcnPwTLXzm%2FQICFcn3w%3D%3D',
    's': '4CnZ%2FgPXtzK8efa1RmpmLg%3D%3D',
    'u': 'TIX8NflllNXow1Ic/ZoBmze/jwyVQjfsnDydzQqFPGDD79kH58CkQVDgHATBFf'
}

# Current URL from app.py (WORKING VERSION - CONFIRMED)
CURRENT_URL = "https://www3.tcsion.com/iONBizServices/iONWebService?servicekey=WaJkcnPwTLXzm%2FQICFcn3w%3D%3D&s=4CnZ%2FgPXtzK8efa1RmpmLg%3D%3D&u=TIX8NflllNXow1Ic/ZoBmze/jwyVQjfsnDydzQqFPGDD79kH58CkQVDgHATBFfbr"


def print_separator(title):
    """Print a formatted separator"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)


def test_method_1_current_url():
    """Test Method 1: Using the current URL as-is"""
    print_separator("Method 1: Current URL (as-is)")
    print(f"URL: {CURRENT_URL}")
    
    try:
        response = requests.get(CURRENT_URL, timeout=30)
        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS!")
            try:
                data = response.json()
                print(f"Response Type: JSON")
                print(f"Number of records: {len(data) if isinstance(data, list) else 'N/A'}")
                print(f"\nFirst record sample:")
                print(json.dumps(data[0] if isinstance(data, list) and len(data) > 0 else data, indent=2)[:500])
            except:
                print(f"Response Text (first 500 chars):\n{response.text[:500]}")
        else:
            print(f"\n❌ FAILED")
            print(f"Response Text:\n{response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def test_method_2_params_dict():
    """Test Method 2: Using params dictionary (requests handles encoding)"""
    print_separator("Method 2: Params Dictionary (auto-encoded by requests)")
    print(f"Base URL: {BASE_URL}")
    print(f"Params: {PARAMS}")
    
    try:
        response = requests.get(BASE_URL, params=PARAMS, timeout=30)
        print(f"\nActual URL called: {response.url}")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS!")
            try:
                data = response.json()
                print(f"Response Type: JSON")
                print(f"Number of records: {len(data) if isinstance(data, list) else 'N/A'}")
                print(f"\nFirst record sample:")
                print(json.dumps(data[0] if isinstance(data, list) and len(data) > 0 else data, indent=2)[:500])
            except:
                print(f"Response Text (first 500 chars):\n{response.text[:500]}")
        else:
            print(f"\n❌ FAILED")
            print(f"Response Text:\n{response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def test_method_3_manual_url():
    """Test Method 3: Manually construct URL with encoded params"""
    print_separator("Method 3: Manually Constructed URL")
    
    # Build URL manually
    query_string = urlencode(PARAMS_ENCODED, safe='')
    manual_url = f"{BASE_URL}?{query_string}"
    print(f"URL: {manual_url}")
    
    try:
        response = requests.get(manual_url, timeout=30)
        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS!")
            try:
                data = response.json()
                print(f"Response Type: JSON")
                print(f"Number of records: {len(data) if isinstance(data, list) else 'N/A'}")
                print(f"\nFirst record sample:")
                print(json.dumps(data[0] if isinstance(data, list) and len(data) > 0 else data, indent=2)[:500])
            except:
                print(f"Response Text (first 500 chars):\n{response.text[:500]}")
        else:
            print(f"\n❌ FAILED")
            print(f"Response Text:\n{response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def test_method_4_with_headers():
    """Test Method 4: With additional headers"""
    print_separator("Method 4: With Custom Headers")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    
    print(f"Base URL: {BASE_URL}")
    print(f"Params: {PARAMS}")
    print(f"Headers: {headers}")
    
    try:
        response = requests.get(BASE_URL, params=PARAMS, headers=headers, timeout=30)
        print(f"\nActual URL called: {response.url}")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS!")
            try:
                data = response.json()
                print(f"Response Type: JSON")
                print(f"Number of records: {len(data) if isinstance(data, list) else 'N/A'}")
                print(f"\nFirst record sample:")
                print(json.dumps(data[0] if isinstance(data, list) and len(data) > 0 else data, indent=2)[:500])
            except:
                print(f"Response Text (first 500 chars):\n{response.text[:500]}")
        else:
            print(f"\n❌ FAILED")
            print(f"Response Text:\n{response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def test_method_5_verify_false():
    """Test Method 5: Disable SSL verification (use with caution)"""
    print_separator("Method 5: With SSL Verification Disabled")
    print("⚠️  WARNING: SSL verification disabled - use only for testing!")
    
    print(f"Base URL: {BASE_URL}")
    print(f"Params: {PARAMS}")
    
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.get(BASE_URL, params=PARAMS, verify=False, timeout=30)
        print(f"\nActual URL called: {response.url}")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS!")
            try:
                data = response.json()
                print(f"Response Type: JSON")
                print(f"Number of records: {len(data) if isinstance(data, list) else 'N/A'}")
                print(f"\nFirst record sample:")
                print(json.dumps(data[0] if isinstance(data, list) and len(data) > 0 else data, indent=2)[:500])
            except:
                print(f"Response Text (first 500 chars):\n{response.text[:500]}")
        else:
            print(f"\n❌ FAILED")
            print(f"Response Text:\n{response.text[:500]}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def main():
    """Run all test methods"""
    print("\n" + "🔍 API CONNECTION TEST SUITE".center(80, "="))
    print("\nTesting TCS iON API endpoint with different configurations...")
    print("This will help identify the correct way to call the API.\n")
    
    # Run all tests
    test_method_1_current_url()
    test_method_2_params_dict()
    test_method_3_manual_url()
    test_method_4_with_headers()
    test_method_5_verify_false()
    
    # Summary
    print_separator("TEST COMPLETE")
    print("\n📋 NEXT STEPS:")
    print("1. Review which method(s) succeeded (marked with ✅)")
    print("2. If a method worked, note the exact URL and parameters used")
    print("3. Update app.py with the working configuration")
    print("4. Set USE_LOCAL_DATA = False in app.py to use live API")
    print("\n💡 TIP: If all methods fail, check:")
    print("   - Network connectivity")
    print("   - API credentials validity")
    print("   - Firewall/proxy settings")
    print("   - API endpoint availability")
    print("\n")


if __name__ == "__main__":
    main()
