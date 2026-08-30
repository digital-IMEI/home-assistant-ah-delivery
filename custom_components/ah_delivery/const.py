"""Constants for the Albert Heijn Delivery integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ah_delivery"
NAME = "Albert Heijn Delivery"
PLATFORMS = [Platform.SENSOR]

API_BASE_URL = "https://api.ah.nl"
LOGIN_BASE_URL = "https://login.ah.nl"
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"
APPLICATION = "AHWEBSHOP"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_MEMBER_ID = "member_id"

TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
ETA_MAX_AGE = timedelta(minutes=10)

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=30)
UPDATE_WITHIN_24H = timedelta(minutes=15)
UPDATE_WITHIN_3H = timedelta(minutes=3)
UPDATE_ACTIVE_ETA = timedelta(minutes=3)

BASE_FULFILLMENTS_QUERY = """
query OrderFulfillments {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      statusCode
      statusDescription
      shoppingType
      transactionCompleted
      modifiable
      delivery {
        status
        method
        slot {
          date
          dateDisplay
          timeDisplay
          startTime
          endTime
        }
      }
    }
  }
}
"""

# Deliberately optional. The currently verified appie-go query does not request ETA.
# If AH exposes these fields, this richer query is used. Any GraphQL schema rejection
# automatically downgrades to BASE_FULFILLMENTS_QUERY without breaking slot data.
RICH_FULFILLMENTS_QUERY = """
query OrderFulfillments {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      statusCode
      statusDescription
      shoppingType
      transactionCompleted
      modifiable
      delivery {
        status
        method
        slot {
          date
          dateDisplay
          timeDisplay
          startTime
          endTime
        }
        eta {
          status
          estimated
          lower
          upper
        }
      }
    }
  }
}
"""
