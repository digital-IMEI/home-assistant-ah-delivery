"""Constants for the Albert Heijn Delivery integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ah_delivery"
NAME = "Albert Heijn Delivery"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

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
ETA_MAX_AGE = timedelta(minutes=15)

# Adaptive polling. Far-away deliveries need very little API traffic, while the
# delivery day becomes progressively more responsive as arrival approaches.
DEFAULT_UPDATE_INTERVAL = timedelta(hours=3)
UPDATE_MORE_THAN_7D = timedelta(hours=6)
UPDATE_WITHIN_7D = timedelta(hours=3)
UPDATE_WITHIN_48H = timedelta(hours=1)
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

RICH_FULFILLMENTS_QUERY = """
query OrderFulfillmentsDiagnostics {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      statusCode
      statusDescription
      shoppingType
      transactionCompleted
      modifiable
      cancellable
      reopenable
      closingDateTime
      delivery {
        status
        method
        deliveryMessage
        shiftCode
        homeShopCenterId
        ride {
          number
          sequenceNumber
          homeShopCenterId
        }
        eta {
          status
          estimated
          lower
          upper
        }
        slot {
          date
          dateDisplay
          dateDisplayShort
          timeDisplay
          dayDisplay
          startTime
          endTime
        }
      }
    }
  }
}
"""

ETA_PROBE_QUERY = """
query OrderFulfillmentsEtaProbe {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      delivery {
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

RIDE_PROBE_QUERY = """
query OrderFulfillmentsRideProbe {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      delivery {
        status
        method
        deliveryMessage
        shiftCode
        homeShopCenterId
        ride {
          number
          sequenceNumber
          homeShopCenterId
        }
        slot {
          date
          dateDisplay
          dateDisplayShort
          timeDisplay
          dayDisplay
          startTime
          endTime
        }
      }
    }
  }
}
"""

# Verified in appie-go's current AH API documentation. The order id is inserted as
# an integer literal so the existing proven GraphQL request path can be reused
# without changing authentication or the working fulfillment calls.
TRACK_TRACE_QUERY_TEMPLATE = """
query FetchOrderTrackTrace {
  order(id: __ORDER_ID__) {
    __typename
    delivery {
      __typename
      trackAndTraceV2 {
        __typename
        orderId
        type
        orderType
        message
        etaBlock {
          __typename
          range {
            __typename
            start
            end
          }
        }
        realisedDeliveryTime
      }
    }
  }
}
"""
