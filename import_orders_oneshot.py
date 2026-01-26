#!/usr/bin/env python3
"""
Jednorazowy skrypt do importu zamówień i uczestników do bazy.
Bezpieczny - używa ON CONFLICT (duplikaty są aktualizowane, nie zduplikowane).

Użycie:
    python import_orders_oneshot.py

Wymaga: DATABASE_URL w środowisku (lub .env)
"""

import os
import sys

# Załaduj .env jeśli istnieje
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Importuj funkcje z pg_storage
import pg_storage

# ============================================================================
# DANE DO IMPORTU (wklejone z Zoho Backstage)
# ============================================================================

EVENT_ID = "24311000000687006"
EVENT_NAME = "Amoz Connect Warszawa"

ORDERS_DATA = [
    {
      "id": "24311000000824097",
      "order_by": "manager@meaclinic.pl",
      "status": 0,
      "status_string": "placed",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": None,
        "state": None,
        "country": None,
        "zipcode": None,
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 1,
      "payment_status_string": "paid",
      "contact": {
        "purchaser_first_name": "Marta",
        "purchaser_last_name": "Szafarczyk   R ycka",
        "purchaser_email": "manager@meaclinic.pl",
        "purchaser_mobile_no": "+48693520927"
      },
      "created_by": {
        "id": "24311000000824093",
        "email": "manager@meaclinic.pl",
        "first_name": "Marta",
        "last_name": "Szafarczyk   R ycka",
        "company": "Mea Clinic",
        "designation": None,
        "telephone": "+48693520927"
      },
      "payments": [],
      "created_time": "2026-01-23T10:10:13Z",
      "last_modified_time": "2026-01-23T10:10:13Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008240971",
          "base_price": 568.29,
          "discount": 568.29,
          "service_fee": 0,
          "tax": 0,
          "total": 0,
          "promo_code": "karolina_k_100",
          "discount_applied": "100.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 1,
          "payment_status_string": "paid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": True,
          "contact": {
            "first_name": "Marta",
            "last_name": "Szafarczyk   R ycka",
            "email": "manager@meaclinic.pl",
            "company_name": "Mea Clinic"
          },
          "created_by": {
            "id": "24311000000824093",
            "email": "manager@meaclinic.pl",
            "first_name": "Marta",
            "last_name": "Szafarczyk   R ycka",
            "company": "Mea Clinic",
            "designation": None,
            "telephone": "+48693520927"
          },
          "created_time": "2026-01-23T10:10:14Z",
          "last_modified_by": {
            "id": "24311000000824093",
            "email": "manager@meaclinic.pl",
            "first_name": "Marta",
            "last_name": "Szafarczyk   R ycka",
            "company": "Mea Clinic",
            "designation": None,
            "telephone": "+48693520927"
          },
          "last_modified_time": "2026-01-23T10:10:14Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000824093",
        "email": "manager@meaclinic.pl",
        "first_name": "Marta",
        "last_name": "Szafarczyk   R ycka",
        "company": "Mea Clinic",
        "designation": None,
        "telephone": "+48693520927"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 568.29,
        "service_fee": 0,
        "tax": 0,
        "tax_percent": 0,
        "total": 0,
        "tax_name": None,
        "promo_code": "karolina_k_100",
        "discount_applied": "100.00%"
      }
    },
    {
      "id": "24311000000829018",
      "order_by": "krzysztof.baczek@poczta.fm",
      "status": 0,
      "status_string": "placed",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Online - link do p atno ci na platformie Stripe na maila",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": "ul. Jana Sebastiana Bacha 2",
        "streetAddress2": None,
        "city": "Warszawa",
        "state": None,
        "country": None,
        "zipcode": "02-743",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "krzysztof.baczek@poczta.fm",
        "purchaser_mobile_no": "+48692914102",
        "purchaser_last_name": "B czek",
        "purchaser_first_name": "Krzysztof"
      },
      "created_by": {
        "id": "24311000000829013",
        "email": "krzysztof.baczek@poczta.fm",
        "first_name": "Krzysztof",
        "last_name": "B czek",
        "company": "KRAJMED CENTRUM MEDYCZNE",
        "designation": None,
        "telephone": "+48692914102"
      },
      "payments": [],
      "created_time": "2026-01-23T10:01:00Z",
      "last_modified_time": "2026-01-23T10:01:00Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008290181",
          "base_price": 568.29,
          "discount": 0,
          "service_fee": 0,
          "tax": 130.71,
          "total": 699,
          "promo_code": None,
          "discount_applied": None,
          "status": 0,
          "status_string": "placed",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": False,
          "contact": {
            "first_name": "Krzysztof",
            "last_name": "B czek",
            "email": "krzysztof.baczek@poczta.fm",
            "company_name": "KRAJMED CENTRUM MEDYCZNE"
          },
          "created_by": {
            "id": "24311000000829013",
            "email": "krzysztof.baczek@poczta.fm",
            "first_name": "Krzysztof",
            "last_name": "B czek",
            "company": "KRAJMED CENTRUM MEDYCZNE",
            "designation": None,
            "telephone": "+48692914102"
          },
          "created_time": "2026-01-23T10:01:01Z",
          "last_modified_by": {
            "id": "24311000000829013",
            "email": "krzysztof.baczek@poczta.fm",
            "first_name": "Krzysztof",
            "last_name": "B czek",
            "company": "KRAJMED CENTRUM MEDYCZNE",
            "designation": None,
            "telephone": "+48692914102"
          },
          "last_modified_time": "2026-01-23T10:01:01Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000829013",
        "email": "krzysztof.baczek@poczta.fm",
        "first_name": "Krzysztof",
        "last_name": "B czek",
        "company": "KRAJMED CENTRUM MEDYCZNE",
        "designation": None,
        "telephone": "+48692914102"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 0,
        "service_fee": 0,
        "tax": 130.71,
        "tax_percent": 23,
        "total": 699,
        "tax_name": "VAT",
        "promo_code": None,
        "discount_applied": None
      }
    },
    {
      "id": "24311000000824074",
      "order_by": "biuro@nzozlomianki.pl",
      "status": 0,
      "status_string": "placed",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Faktura Pro forma - p atno   na konto bankowe",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": "ul. Warszawska 31",
        "streetAddress2": None,
        "city": " omianki ",
        "state": None,
        "country": None,
        "zipcode": "05-092",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "biuro@nzozlomianki.pl",
        "purchaser_mobile_no": "+48501025620",
        "purchaser_last_name": "Lenart",
        "purchaser_first_name": "Anna",
        "tax_registration_no": "5261627433"
      },
      "created_by": {
        "id": "24311000000824069",
        "email": "biuro@nzozlomianki.pl",
        "first_name": "Anna",
        "last_name": "Lenart",
        "company": "NZOZ  omianki",
        "designation": None,
        "telephone": "+48501025620"
      },
      "payments": [],
      "created_time": "2026-01-23T08:45:20Z",
      "last_modified_time": "2026-01-23T08:45:20Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008240741",
          "base_price": 568.29,
          "discount": 85.24,
          "service_fee": 0,
          "tax": 111.1,
          "total": 594.15,
          "promo_code": "karolina_k_15",
          "discount_applied": "15.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": False,
          "contact": {
            "first_name": "Anna",
            "last_name": "Lenart",
            "email": "biuro@nzozlomianki.pl",
            "company_name": "NZOZ  omianki"
          },
          "created_by": {
            "id": "24311000000824069",
            "email": "biuro@nzozlomianki.pl",
            "first_name": "Anna",
            "last_name": "Lenart",
            "company": "NZOZ  omianki",
            "designation": None,
            "telephone": "+48501025620"
          },
          "created_time": "2026-01-23T08:45:20Z",
          "last_modified_by": {
            "id": "24311000000824069",
            "email": "biuro@nzozlomianki.pl",
            "first_name": "Anna",
            "last_name": "Lenart",
            "company": "NZOZ  omianki",
            "designation": None,
            "telephone": "+48501025620"
          },
          "last_modified_time": "2026-01-23T08:45:20Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000824069",
        "email": "biuro@nzozlomianki.pl",
        "first_name": "Anna",
        "last_name": "Lenart",
        "company": "NZOZ  omianki",
        "designation": None,
        "telephone": "+48501025620"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 85.24,
        "service_fee": 0,
        "tax": 111.1,
        "tax_percent": 23,
        "total": 594.15,
        "tax_name": "VAT",
        "promo_code": "karolina_k_15",
        "discount_applied": "15.00%"
      }
    },
    {
      "id": "24311000000824028",
      "order_by": "adminzoho@medidesk.com",
      "status": 1,
      "status_string": "cancelled",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Faktura Pro forma - p atno   na konto bankowe",
      "source": 1,
      "source_string": "backstage",
      "order_comment": "erfergfe",
      "billing_address": {
        "name": None,
        "streetAddress1": "ul. Belwederska 23",
        "streetAddress2": None,
        "city": "Warszawa",
        "state": None,
        "country": None,
        "zipcode": "00-761",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "adminzoho@medidesk.com",
        "purchaser_mobile_no": "+48888469553",
        "purchaser_last_name": "Pingwin",
        "purchaser_first_name": "Gertura"
      },
      "canceled_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "created_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "payments": [],
      "created_time": "2026-01-22T13:34:10Z",
      "last_modified_time": "2026-01-23T11:48:22Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008240281",
          "base_price": 568.29,
          "discount": 0,
          "service_fee": 0,
          "tax": 130.71,
          "total": 699,
          "promo_code": None,
          "discount_applied": None,
          "status": 1,
          "status_string": "cancelled",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "comment": "erfergfe",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "canceled_by": {
            "id": "24311000000735001",
            "email": "adminzoho@medidesk.com",
            "first_name": "adminzoho",
            "last_name": "ohooo",
            "company": None,
            "designation": None,
            "telephone": "+48888469553"
          },
          "issue_ticket": False,
          "contact": {
            "first_name": "Gertura",
            "last_name": "Pingwin",
            "email": "adminzoho@medidesk.com"
          },
          "created_by": {
            "id": "24311000000735001",
            "email": "adminzoho@medidesk.com",
            "first_name": "adminzoho",
            "last_name": "ohooo",
            "company": None,
            "designation": None,
            "telephone": "+48888469553"
          },
          "created_time": "2026-01-22T13:34:10Z",
          "last_modified_by": {
            "id": "24311000000735001",
            "email": "adminzoho@medidesk.com",
            "first_name": "adminzoho",
            "last_name": "ohooo",
            "company": None,
            "designation": None,
            "telephone": "+48888469553"
          },
          "last_modified_time": "2026-01-23T11:48:22Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 0,
        "service_fee": 0,
        "tax": 130.71,
        "tax_percent": 23,
        "total": 699,
        "tax_name": "VAT",
        "promo_code": None,
        "discount_applied": None
      }
    },
    {
      "id": "24311000000798037",
      "order_by": "r.hila@szpitalzelazna.pl",
      "status": 0,
      "status_string": "placed",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Faktura Pro forma - p atno   na konto bankowe",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": " elazna 90",
        "streetAddress2": None,
        "city": "Warszawa",
        "state": None,
        "country": None,
        "zipcode": "01-004",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "r.hila@szpitalzelazna.pl",
        "purchaser_mobile_no": "+48880349927",
        "purchaser_last_name": "Hila",
        "purchaser_first_name": "Romana",
        "tax_registration_no": "5270104746"
      },
      "created_by": {
        "id": "24311000000798032",
        "email": "r.hila@szpitalzelazna.pl",
        "first_name": "Romana",
        "last_name": "Hila",
        "company": "Centrum Medyczne   elazna ",
        "designation": None,
        "telephone": "+48880349927"
      },
      "payments": [],
      "created_time": "2026-01-22T08:44:49Z",
      "last_modified_time": "2026-01-22T08:44:49Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000007980372",
          "base_price": 399,
          "discount": 59.85,
          "service_fee": 0,
          "tax": 78,
          "total": 417.15,
          "promo_code": "paulina_15",
          "discount_applied": "15.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "ticket_name": "*Bilet Connect +",
          "ticket_class_id": "24311000000692095",
          "issue_ticket": False,
          "contact": {
            "first_name": "Marta",
            "last_name": "Rysiawa",
            "email": "m.rysiawa@szpitalzelazna.pl",
            "company_name": "Centrum Medyczne   elazna "
          },
          "created_by": {
            "id": "24311000000798032",
            "email": "r.hila@szpitalzelazna.pl",
            "first_name": "Romana",
            "last_name": "Hila",
            "company": "Centrum Medyczne   elazna ",
            "designation": None,
            "telephone": "+48880349927"
          },
          "created_time": "2026-01-22T08:44:49Z",
          "last_modified_by": {
            "id": "24311000000798032",
            "email": "r.hila@szpitalzelazna.pl",
            "first_name": "Romana",
            "last_name": "Hila",
            "company": "Centrum Medyczne   elazna ",
            "designation": None,
            "telephone": "+48880349927"
          },
          "last_modified_time": "2026-01-22T08:44:49Z"
        },
        {
          "id": "243110000007980371",
          "base_price": 399,
          "discount": 59.85,
          "service_fee": 0,
          "tax": 78.01,
          "total": 417.16,
          "promo_code": "paulina_15",
          "discount_applied": "15.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "ticket_name": "*Bilet Connect +",
          "ticket_class_id": "24311000000692095",
          "issue_ticket": False,
          "contact": {
            "first_name": "Romana",
            "last_name": "Hila",
            "email": "r.hila@szpitalzelazna.pl",
            "company_name": "Centrum Medyczne   elazna "
          },
          "created_by": {
            "id": "24311000000798032",
            "email": "r.hila@szpitalzelazna.pl",
            "first_name": "Romana",
            "last_name": "Hila",
            "company": "Centrum Medyczne   elazna ",
            "designation": None,
            "telephone": "+48880349927"
          },
          "created_time": "2026-01-22T08:44:49Z",
          "last_modified_by": {
            "id": "24311000000798032",
            "email": "r.hila@szpitalzelazna.pl",
            "first_name": "Romana",
            "last_name": "Hila",
            "company": "Centrum Medyczne   elazna ",
            "designation": None,
            "telephone": "+48880349927"
          },
          "last_modified_time": "2026-01-22T08:44:49Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000798032",
        "email": "r.hila@szpitalzelazna.pl",
        "first_name": "Romana",
        "last_name": "Hila",
        "company": "Centrum Medyczne   elazna ",
        "designation": None,
        "telephone": "+48880349927"
      },
      "cost": {
        "sub_total": 798,
        "discount": 119.7,
        "service_fee": 0,
        "tax": 156.01,
        "tax_percent": 23,
        "total": 834.31,
        "tax_name": "VAT",
        "promo_code": "paulina_15",
        "discount_applied": "15.00%"
      }
    },
    {
      "id": "24311000000810226",
      "order_by": "webinar2@digitalunity.pl",
      "status": 1,
      "status_string": "cancelled",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Faktura Pro forma - p atno   na konto bankowe",
      "source": 1,
      "source_string": "backstage",
      "order_comment": "ewd",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": "Warszawa",
        "state": None,
        "country": None,
        "zipcode": "00-712",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "webinar2@digitalunity.pl",
        "purchaser_mobile_no": "+48888469553",
        "purchaser_last_name": "Ochnik",
        "purchaser_first_name": "Katarzyna",
        "tax_registration_no": "9710668048"
      },
      "canceled_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "created_by": {
        "id": "24311000000613111",
        "email": "webinar2@digitalunity.pl",
        "first_name": "ee",
        "last_name": "ee",
        "company": "Tr bkowo2",
        "designation": None
      },
      "payments": [],
      "created_time": "2026-01-21T09:58:40Z",
      "last_modified_time": "2026-01-21T12:55:16Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008102261",
          "base_price": 568.29,
          "discount": 0,
          "service_fee": 0,
          "tax": 130.71,
          "total": 699,
          "promo_code": None,
          "discount_applied": None,
          "status": 1,
          "status_string": "cancelled",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "comment": "ewd",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "canceled_by": {
            "id": "24311000000735001",
            "email": "adminzoho@medidesk.com",
            "first_name": "adminzoho",
            "last_name": "ohooo",
            "company": None,
            "designation": None,
            "telephone": "+48888469553"
          },
          "issue_ticket": False,
          "contact": {
            "first_name": "Katarzyna",
            "last_name": "Ochnik",
            "email": "webinar2@digitalunity.pl"
          },
          "created_by": {
            "id": "24311000000613111",
            "email": "webinar2@digitalunity.pl",
            "first_name": "ee",
            "last_name": "ee",
            "company": "Tr bkowo2",
            "designation": None
          },
          "created_time": "2026-01-21T09:58:40Z",
          "last_modified_by": {
            "id": "24311000000613111",
            "email": "webinar2@digitalunity.pl",
            "first_name": "ee",
            "last_name": "ee",
            "company": "Tr bkowo2",
            "designation": None
          },
          "last_modified_time": "2026-01-21T12:55:16Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 0,
        "service_fee": 0,
        "tax": 130.71,
        "tax_percent": 23,
        "total": 699,
        "tax_name": "VAT",
        "promo_code": None,
        "discount_applied": None
      }
    },
    {
      "id": "24311000000810204",
      "order_by": "webinar1@digitalunity.pl",
      "status": 1,
      "status_string": "cancelled",
      "payment_type": 2,
      "payment_type_string": "others",
      "payment_option_name": "Online - link do p atno ci na platformie Stripe na maila",
      "source": 1,
      "source_string": "backstage",
      "order_comment": "wedwe",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": "Warszawa",
        "state": None,
        "country": None,
        "zipcode": "00-712",
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 2,
      "payment_status_string": "unpaid",
      "contact": {
        "purchaser_email": "webinar1@digitalunity.pl",
        "purchaser_mobile_no": "+48888469553",
        "purchaser_last_name": "Ochnik",
        "purchaser_first_name": "Katarzyna",
        "tax_registration_no": "9710668048"
      },
      "canceled_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "created_by": {
        "id": "24311000000597098",
        "email": "webinar1@digitalunity.pl",
        "first_name": "Katarzyna",
        "last_name": "Mierzejewska-Pingwin",
        "company": "Zawiadowca Haosem Sp. z o.o.",
        "designation": "Prezes Zarz du",
        "telephone": "+48888469553"
      },
      "payments": [],
      "created_time": "2026-01-21T09:57:21Z",
      "last_modified_time": "2026-01-21T12:55:01Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008102041",
          "base_price": 568.29,
          "discount": 0,
          "service_fee": 0,
          "tax": 130.71,
          "total": 699,
          "promo_code": None,
          "discount_applied": None,
          "status": 1,
          "status_string": "cancelled",
          "payment_status": 2,
          "payment_status_string": "unpaid",
          "comment": "wedwe",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "canceled_by": {
            "id": "24311000000735001",
            "email": "adminzoho@medidesk.com",
            "first_name": "adminzoho",
            "last_name": "ohooo",
            "company": None,
            "designation": None,
            "telephone": "+48888469553"
          },
          "issue_ticket": False,
          "contact": {
            "first_name": "Katarzyna",
            "last_name": "Ochnik",
            "email": "webinar1@digitalunity.pl"
          },
          "created_by": {
            "id": "24311000000597098",
            "email": "webinar1@digitalunity.pl",
            "first_name": "Katarzyna",
            "last_name": "Mierzejewska-Pingwin",
            "company": "Zawiadowca Haosem Sp. z o.o.",
            "designation": "Prezes Zarz du",
            "telephone": "+48888469553"
          },
          "created_time": "2026-01-21T09:57:22Z",
          "last_modified_by": {
            "id": "24311000000597098",
            "email": "webinar1@digitalunity.pl",
            "first_name": "Katarzyna",
            "last_name": "Mierzejewska-Pingwin",
            "company": "Zawiadowca Haosem Sp. z o.o.",
            "designation": "Prezes Zarz du",
            "telephone": "+48888469553"
          },
          "last_modified_time": "2026-01-21T12:55:01Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000735001",
        "email": "adminzoho@medidesk.com",
        "first_name": "adminzoho",
        "last_name": "ohooo",
        "company": None,
        "designation": None,
        "telephone": "+48888469553"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 0,
        "service_fee": 0,
        "tax": 130.71,
        "tax_percent": 23,
        "total": 699,
        "tax_name": "VAT",
        "promo_code": None,
        "discount_applied": None
      }
    },
    {
      "id": "24311000000803075",
      "order_by": "m.czepczynski@nzozlomianki.pl",
      "status": 0,
      "status_string": "placed",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": None,
        "state": None,
        "country": None,
        "zipcode": None,
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 1,
      "payment_status_string": "paid",
      "contact": {
        "purchaser_first_name": "Mariusz",
        "purchaser_last_name": "Czepczy ski",
        "purchaser_email": "m.czepczynski@nzozlomianki.pl",
        "purchaser_mobile_no": "+48608488269"
      },
      "created_by": {
        "id": "24311000000803071",
        "email": "m.czepczynski@nzozlomianki.pl",
        "first_name": "Mariusz",
        "last_name": "Czepczy ski",
        "company": "NZOZ  omianki",
        "designation": None,
        "telephone": "+48608488269"
      },
      "payments": [],
      "created_time": "2026-01-19T12:40:08Z",
      "last_modified_time": "2026-01-19T12:40:08Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008030751",
          "base_price": 568.29,
          "discount": 568.29,
          "service_fee": 0,
          "tax": 0,
          "total": 0,
          "promo_code": "karolina_k_100",
          "discount_applied": "100.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 1,
          "payment_status_string": "paid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": True,
          "contact": {
            "first_name": "Mariusz",
            "last_name": "Czepczy ski",
            "email": "m.czepczynski@nzozlomianki.pl",
            "company_name": "NZOZ  omianki"
          },
          "created_by": {
            "id": "24311000000803071",
            "email": "m.czepczynski@nzozlomianki.pl",
            "first_name": "Mariusz",
            "last_name": "Czepczy ski",
            "company": "NZOZ  omianki",
            "designation": None,
            "telephone": "+48608488269"
          },
          "created_time": "2026-01-19T12:40:08Z",
          "last_modified_by": {
            "id": "24311000000803071",
            "email": "m.czepczynski@nzozlomianki.pl",
            "first_name": "Mariusz",
            "last_name": "Czepczy ski",
            "company": "NZOZ  omianki",
            "designation": None,
            "telephone": "+48608488269"
          },
          "last_modified_time": "2026-01-19T12:40:08Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000803071",
        "email": "m.czepczynski@nzozlomianki.pl",
        "first_name": "Mariusz",
        "last_name": "Czepczy ski",
        "company": "NZOZ  omianki",
        "designation": None,
        "telephone": "+48608488269"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 568.29,
        "service_fee": 0,
        "tax": 0,
        "tax_percent": 0,
        "total": 0,
        "tax_name": None,
        "promo_code": "karolina_k_100",
        "discount_applied": "100.00%"
      }
    },
    {
      "id": "24311000000803054",
      "order_by": "justyna.jurak@spkso.waw.pl",
      "status": 0,
      "status_string": "placed",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": None,
        "state": None,
        "country": None,
        "zipcode": None,
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 1,
      "payment_status_string": "paid",
      "contact": {
        "purchaser_first_name": "Justyna",
        "purchaser_last_name": "Jurak",
        "purchaser_email": "justyna.jurak@spkso.waw.pl",
        "purchaser_mobile_no": "+48574594002"
      },
      "created_by": {
        "id": "24311000000803050",
        "email": "justyna.jurak@spkso.waw.pl",
        "first_name": "Justyna",
        "last_name": "Jurak",
        "company": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny",
        "designation": None,
        "telephone": "+48574594002"
      },
      "payments": [],
      "created_time": "2026-01-19T12:38:20Z",
      "last_modified_time": "2026-01-19T12:38:20Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008030541",
          "base_price": 568.29,
          "discount": 568.29,
          "service_fee": 0,
          "tax": 0,
          "total": 0,
          "promo_code": "karolina_k_100",
          "discount_applied": "100.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 1,
          "payment_status_string": "paid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": True,
          "contact": {
            "first_name": "Justyna",
            "last_name": "Jurak",
            "email": "justyna.jurak@spkso.waw.pl",
            "company_name": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny"
          },
          "created_by": {
            "id": "24311000000803050",
            "email": "justyna.jurak@spkso.waw.pl",
            "first_name": "Justyna",
            "last_name": "Jurak",
            "company": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny",
            "designation": None,
            "telephone": "+48574594002"
          },
          "created_time": "2026-01-19T12:38:20Z",
          "last_modified_by": {
            "id": "24311000000803050",
            "email": "justyna.jurak@spkso.waw.pl",
            "first_name": "Justyna",
            "last_name": "Jurak",
            "company": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny",
            "designation": None,
            "telephone": "+48574594002"
          },
          "last_modified_time": "2026-01-19T12:38:20Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000803050",
        "email": "justyna.jurak@spkso.waw.pl",
        "first_name": "Justyna",
        "last_name": "Jurak",
        "company": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny",
        "designation": None,
        "telephone": "+48574594002"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 568.29,
        "service_fee": 0,
        "tax": 0,
        "tax_percent": 0,
        "total": 0,
        "tax_name": None,
        "promo_code": "karolina_k_100",
        "discount_applied": "100.00%"
      }
    },
    {
      "id": "24311000000803031",
      "order_by": "d.siwak@medicers.eu",
      "status": 0,
      "status_string": "placed",
      "source": 1,
      "source_string": "backstage",
      "billing_address": {
        "name": None,
        "streetAddress1": None,
        "streetAddress2": None,
        "city": None,
        "state": None,
        "country": None,
        "zipcode": None,
        "state_data": None,
        "country_data": None
      },
      "refund_policy": -1,
      "cancellation_policy_details": {
        "policyType": -1,
        "intervals": []
      },
      "origin": 1,
      "origin_string": "site",
      "payment_status": 1,
      "payment_status_string": "paid",
      "contact": {
        "purchaser_first_name": "Dorota",
        "purchaser_last_name": "Siwak",
        "purchaser_email": "d.siwak@medicers.eu",
        "purchaser_mobile_no": "+48694430304"
      },
      "created_by": {
        "id": "24311000000803027",
        "email": "d.siwak@medicers.eu",
        "first_name": "Dorota",
        "last_name": "Siwak",
        "company": "CM Medicers",
        "designation": None,
        "telephone": "+48694430304"
      },
      "payments": [],
      "created_time": "2026-01-19T12:36:29Z",
      "last_modified_time": "2026-01-19T12:36:29Z",
      "refunds": [],
      "tickets": [
        {
          "id": "243110000008030311",
          "base_price": 568.29,
          "discount": 568.29,
          "service_fee": 0,
          "tax": 0,
          "total": 0,
          "promo_code": "karolina_k_100",
          "discount_applied": "100.00%",
          "status": 0,
          "status_string": "placed",
          "payment_status": 1,
          "payment_status_string": "paid",
          "ticket_name": "Bilet Connect",
          "ticket_class_id": "24311000000692096",
          "issue_ticket": True,
          "contact": {
            "first_name": "Dorota",
            "last_name": "Siwak",
            "email": "d.siwak@medicers.eu",
            "company_name": "CM Medicers"
          },
          "created_by": {
            "id": "24311000000803027",
            "email": "d.siwak@medicers.eu",
            "first_name": "Dorota",
            "last_name": "Siwak",
            "company": "CM Medicers",
            "designation": None,
            "telephone": "+48694430304"
          },
          "created_time": "2026-01-19T12:36:29Z",
          "last_modified_by": {
            "id": "24311000000803027",
            "email": "d.siwak@medicers.eu",
            "first_name": "Dorota",
            "last_name": "Siwak",
            "company": "CM Medicers",
            "designation": None,
            "telephone": "+48694430304"
          },
          "last_modified_time": "2026-01-19T12:36:29Z"
        }
      ],
      "last_modified_by": {
        "id": "24311000000803027",
        "email": "d.siwak@medicers.eu",
        "first_name": "Dorota",
        "last_name": "Siwak",
        "company": "CM Medicers",
        "designation": None,
        "telephone": "+48694430304"
      },
      "cost": {
        "sub_total": 568.29,
        "discount": 568.29,
        "service_fee": 0,
        "tax": 0,
        "tax_percent": 0,
        "total": 0,
        "tax_name": None,
        "promo_code": "karolina_k_100",
        "discount_applied": "100.00%"
      }
    }
]

ATTENDEES_DATA = [
    {
      "id": "24311000000829022",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000829018",
      "ticket_id": "243110000008290181",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "krzysztof.baczek@poczta.fm",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": None,
      "contact": {
        "first_name": "Krzysztof",
        "last_name": "B czek",
        "email": "krzysztof.baczek@poczta.fm",
        "company_name": "KRAJMED CENTRUM MEDYCZNE"
      },
      "checked_in": False,
      "created_time": "2026-01-23T10:01:01Z",
      "last_modified_time": "2026-01-23T10:01:01Z"
    },
    {
      "id": "24311000000824101",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000824097",
      "ticket_id": "243110000008240971",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "manager@meaclinic.pl",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_100",
      "contact": {
        "first_name": "Marta",
        "last_name": "Szafarczyk   R ycka",
        "email": "manager@meaclinic.pl",
        "company_name": "Mea Clinic"
      },
      "checked_in": False,
      "created_time": "2026-01-23T10:10:14Z",
      "last_modified_time": "2026-01-23T10:10:14Z"
    },
    {
      "id": "24311000000824078",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000824074",
      "ticket_id": "243110000008240741",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "biuro@nzozlomianki.pl",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_15",
      "contact": {
        "first_name": "Anna",
        "last_name": "Lenart",
        "email": "biuro@nzozlomianki.pl",
        "company_name": "NZOZ  omianki"
      },
      "checked_in": False,
      "created_time": "2026-01-23T08:45:20Z",
      "last_modified_time": "2026-01-23T08:45:20Z"
    },
    {
      "id": "24311000000824032",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000824028",
      "ticket_id": "243110000008240281",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "adminzoho@medidesk.com",
      "status": 0,
      "status_string": "not_attending",
      "affiliate_name": None,
      "promo_code": None,
      "contact": {
        "first_name": "Gertura",
        "last_name": "Pingwin",
        "email": "adminzoho@medidesk.com"
      },
      "checked_in": False,
      "created_time": "2026-01-22T13:34:11Z",
      "last_modified_time": "2026-01-23T11:48:22Z"
    },
    {
      "id": "24311000000810230",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000810226",
      "ticket_id": "243110000008102261",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "webinar2@digitalunity.pl",
      "status": 0,
      "status_string": "not_attending",
      "affiliate_name": None,
      "promo_code": None,
      "contact": {
        "first_name": "Katarzyna",
        "last_name": "Ochnik",
        "email": "webinar2@digitalunity.pl"
      },
      "checked_in": False,
      "created_time": "2026-01-21T09:58:40Z",
      "last_modified_time": "2026-01-21T12:55:16Z"
    },
    {
      "id": "24311000000810208",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000810204",
      "ticket_id": "243110000008102041",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "webinar1@digitalunity.pl",
      "status": 0,
      "status_string": "not_attending",
      "affiliate_name": None,
      "promo_code": None,
      "contact": {
        "first_name": "Katarzyna",
        "last_name": "Ochnik",
        "email": "webinar1@digitalunity.pl"
      },
      "checked_in": False,
      "created_time": "2026-01-21T09:57:22Z",
      "last_modified_time": "2026-01-21T12:55:01Z"
    },
    {
      "id": "24311000000803079",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000803075",
      "ticket_id": "243110000008030751",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "m.czepczynski@nzozlomianki.pl",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_100",
      "contact": {
        "first_name": "Mariusz",
        "last_name": "Czepczy ski",
        "email": "m.czepczynski@nzozlomianki.pl",
        "company_name": "NZOZ  omianki"
      },
      "checked_in": False,
      "created_time": "2026-01-19T12:40:08Z",
      "last_modified_time": "2026-01-19T12:40:08Z"
    },
    {
      "id": "24311000000803058",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000803054",
      "ticket_id": "243110000008030541",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "justyna.jurak@spkso.waw.pl",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_100",
      "contact": {
        "first_name": "Justyna",
        "last_name": "Jurak",
        "email": "justyna.jurak@spkso.waw.pl",
        "company_name": "Samodzielny Publiczny Kliniczny Szpital Okulistyczny"
      },
      "checked_in": False,
      "created_time": "2026-01-19T12:38:21Z",
      "last_modified_time": "2026-01-19T12:38:21Z"
    },
    {
      "id": "24311000000803035",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000803031",
      "ticket_id": "243110000008030311",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "d.siwak@medicers.eu",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_100",
      "contact": {
        "first_name": "Dorota",
        "last_name": "Siwak",
        "email": "d.siwak@medicers.eu",
        "company_name": "CM Medicers"
      },
      "checked_in": False,
      "created_time": "2026-01-19T12:36:29Z",
      "last_modified_time": "2026-01-19T12:36:29Z"
    },
    {
      "id": "24311000000803014",
      "portal": "20101549222",
      "event_id": "24311000000687006",
      "order_id": "24311000000803010",
      "ticket_id": "243110000008030101",
      "ticket_class_id": "24311000000692096",
      "ticket_name": "Bilet Connect",
      "purchased_by": "anna.tkacz@mimedica.pl",
      "status": 1,
      "status_string": "attending",
      "affiliate_name": None,
      "promo_code": "karolina_k_100",
      "contact": {
        "first_name": "Anna",
        "last_name": "Tkacz",
        "email": "anna.tkacz@mimedica.pl",
        "company_name": "Mimedica"
      },
      "checked_in": False,
      "created_time": "2026-01-19T12:33:45Z",
      "last_modified_time": "2026-01-19T12:33:45Z"
    }
]

# ============================================================================
# MAPOWANIE STATUSÓW
# ============================================================================

def map_order_status(order: dict) -> str:
    """
    Mapuje status z Zoho Backstage na status w naszej bazie.
    
    Zoho:
      - status_string: placed / cancelled
      - payment_status_string: paid / unpaid
    
    Nasza baza:
      - received / pending_payment / paid / failed / cancelled
    """
    if order.get("status_string") == "cancelled":
        return "cancelled"
    
    if order.get("payment_status_string") == "paid":
        return "paid"
    
    return "pending_payment"


def map_participant_status(attendee: dict) -> str:
    """
    Mapuje status uczestnika z Zoho Backstage na status w naszej bazie.
    
    Zoho:
      - status_string: attending / not_attending
    
    Nasza baza:
      - pending / registered / emailed / failed / cancelled
    
    UWAGA: Używamy "emailed" zamiast "registered" żeby oznaczyć
    że mail z biletem już został wysłany (blokada ponownej wysyłki).
    """
    if attendee.get("status_string") == "not_attending":
        return "cancelled"
    # "emailed" oznacza że mail już poszedł - blokuje auto-wysyłkę
    return "emailed"


# ============================================================================
# IMPORT LOGIC
# ============================================================================

def ensure_event_exists():
    """Upewnia się, że event istnieje w bazie (wymagane przez FK)."""
    existing = pg_storage.get_event(EVENT_ID)
    if existing:
        print(f"[OK] Event {EVENT_ID} już istnieje: {existing.get('event_name')}")
        return
    
    print(f"[+] Tworzę event {EVENT_ID} ({EVENT_NAME})...")
    pg_storage.upsert_event(
        event_id=EVENT_ID,
        event_name=EVENT_NAME,
        status="active",
        notes="Import jednorazowy",
        data={"source": "manual_import"},
        is_active=True
    )
    print(f"[OK] Event utworzony")


def import_orders():
    """Importuje zamówienia z obsługą duplikatów (ON CONFLICT)."""
    print(f"\n=== Import {len(ORDERS_DATA)} zamówień ===")
    
    success = 0
    skipped = 0
    errors = 0
    
    for order in ORDERS_DATA:
        order_id = order["id"]
        contact = order.get("contact", {})
        cost = order.get("cost", {})
        
        try:
            db_status = map_order_status(order)
            
            result = pg_storage.upsert_order(
                event_order_id=order_id,
                event_id=EVENT_ID,
                purchaser_email=contact.get("purchaser_email"),
                purchaser_first_name=contact.get("purchaser_first_name"),
                purchaser_last_name=contact.get("purchaser_last_name"),
                purchaser_phone=contact.get("purchaser_mobile_no"),
                purchaser_nip=contact.get("tax_registration_no"),
                payment_option_name=order.get("payment_option_name"),
                payment_type=order.get("payment_type"),
                promo_code=cost.get("promo_code"),
                total=cost.get("total"),
                currency="PLN",
                status=db_status,
                raw=order
            )
            
            if result:
                print(f"  [OK] Order {order_id} -> {db_status}")
                success += 1
            else:
                print(f"  [?] Order {order_id} - brak wyniku")
                skipped += 1
                
        except Exception as e:
            print(f"  [ERR] Order {order_id}: {e}")
            errors += 1
    
    print(f"\nZamówienia: {success} OK, {skipped} pominięte, {errors} błędy")
    return success, errors


def import_participants():
    """Importuje uczestników z obsługą duplikatów (ON CONFLICT)."""
    print(f"\n=== Import {len(ATTENDEES_DATA)} uczestników ===")
    
    success = 0
    errors = 0
    
    for att in ATTENDEES_DATA:
        order_id = att["order_id"]
        ticket_id = att["ticket_id"]
        contact = att.get("contact", {})
        
        try:
            db_status = map_participant_status(att)
            
            result = pg_storage.save_participant(
                event_order_id=order_id,
                ticket_id=ticket_id,
                ticket_class_id=att.get("ticket_class_id", ""),
                email=contact.get("email", ""),
                first_name=contact.get("first_name", ""),
                last_name=contact.get("last_name", ""),
                phone="",  # attendee nie ma telefonu
                status=db_status,
                data={
                    "zoho_attendee_id": att["id"],
                    "company_name": contact.get("company_name"),
                    "promo_code": att.get("promo_code"),
                    "ticket_name": att.get("ticket_name"),
                    "checked_in": att.get("checked_in", False),
                }
            )
            
            if result:
                print(f"  [OK] Attendee {att['id']} -> {contact.get('email')} ({db_status})")
                success += 1
            else:
                print(f"  [?] Attendee {att['id']} - brak wyniku")
                
        except Exception as e:
            print(f"  [ERR] Attendee {att['id']}: {e}")
            errors += 1
    
    print(f"\nUczestnicy: {success} OK, {errors} błędy")
    return success, errors


def import_participants_from_tickets():
    """
    Importuje uczestników z biletów w zamówieniach.
    Używane gdy attendees_sample nie zawiera wszystkich danych.
    """
    print(f"\n=== Import uczestników z biletów zamówień ===")
    
    success = 0
    errors = 0
    
    for order in ORDERS_DATA:
        order_id = order["id"]
        tickets = order.get("tickets", [])
        
        for ticket in tickets:
            ticket_id = ticket["id"]
            contact = ticket.get("contact", {})
            
            # Ustal status na podstawie biletu
            # "emailed" oznacza że mail już poszedł - blokuje auto-wysyłkę
            if ticket.get("status_string") == "cancelled":
                db_status = "cancelled"
            elif ticket.get("payment_status_string") == "paid":
                db_status = "emailed"  # mail z biletem już poszedł
            else:
                db_status = "pending"
            
            try:
                result = pg_storage.save_participant(
                    event_order_id=order_id,
                    ticket_id=ticket_id,
                    ticket_class_id=ticket.get("ticket_class_id", ""),
                    email=contact.get("email", ""),
                    first_name=contact.get("first_name", ""),
                    last_name=contact.get("last_name", ""),
                    phone="",
                    status=db_status,
                    data={
                        "company_name": contact.get("company_name"),
                        "ticket_name": ticket.get("ticket_name"),
                        "promo_code": ticket.get("promo_code"),
                        "total": ticket.get("total"),
                        "discount_applied": ticket.get("discount_applied"),
                    }
                )
                
                if result:
                    print(f"  [OK] Ticket {ticket_id} -> {contact.get('email')} ({db_status})")
                    success += 1
                    
            except Exception as e:
                print(f"  [ERR] Ticket {ticket_id}: {e}")
                errors += 1
    
    print(f"\nUczestnicy z biletów: {success} OK, {errors} błędy")
    return success, errors


# ============================================================================
# MAIL LOG - oznaczenie że maile już poszły (blokuje automatyczne wysyłki)
# ============================================================================

def mark_emails_as_sent():
    """
    Dodaje wpisy do mail_log oznaczające że maile potwierdzające już poszły.
    To zapobiega automatycznemu wysyłaniu maili przez system.
    
    Szablony:
    - registration_confirmation: potwierdzenie rejestracji (FOC - 0 PLN)
    - proforma_sent: wysłanie proformy (płatne)
    - participant_ticket: bilet uczestnika
    - internal_order_received: wewnętrzny mail o zamówieniu
    """
    print(f"\n=== Oznaczanie maili jako wysłane (blokada auto-wysyłki) ===")
    
    success = 0
    skipped = 0
    
    for order in ORDERS_DATA:
        order_id = order["id"]
        contact = order.get("contact", {})
        purchaser_email = contact.get("purchaser_email", "")
        cost = order.get("cost", {})
        total = cost.get("total", 0)
        created_time = order.get("created_time", "")
        
        # Pomijamy anulowane zamówienia
        if order.get("status_string") == "cancelled":
            print(f"  [SKIP] Order {order_id} - anulowane, pomijam mail_log")
            skipped += 1
            continue
        
        # Określ jaki typ maila potwierdzającego powinien być
        if total == 0:
            # Bilet za 0 PLN (100% rabat) - registration_confirmation
            template_key = "registration_confirmation"
        else:
            # Płatne zamówienie - proforma_sent lub stripe_payment_link
            payment_option = order.get("payment_option_name", "")
            if "Stripe" in payment_option or "link" in payment_option.lower():
                template_key = "stripe_payment_link"
            else:
                template_key = "proforma_sent"
        
        try:
            # Sprawdź czy wpis już istnieje
            if pg_storage.mail_log_exists(order_id, template_key, "purchaser"):
                print(f"  [EXISTS] Order {order_id} - mail_log {template_key} już istnieje")
                skipped += 1
                continue
            
            # Dodaj wpis do mail_log jako "sent"
            result = pg_storage.save_mail_log(
                event_order_id=order_id,
                direction="purchaser",
                template_key=template_key,
                to_email=purchaser_email,
                subject=f"[IMPORT] Potwierdzenie - {template_key}",
                data={
                    "import_note": "Zaimportowane z Zoho Backstage - mail już wysłany",
                    "original_created_time": created_time,
                }
            )
            
            if result:
                # Oznacz jako wysłany
                mail_id = result.get("id")
                if mail_id:
                    pg_storage.mark_mail_sent(mail_id)
                print(f"  [OK] Order {order_id} -> mail_log {template_key} (purchaser)")
                success += 1
                
        except Exception as e:
            print(f"  [ERR] Order {order_id} mail_log: {e}")
    
    # Dodaj też wpisy dla internal (wewnętrzne powiadomienia)
    print(f"\n  --- Internal mails ---")
    for order in ORDERS_DATA:
        order_id = order["id"]
        
        if order.get("status_string") == "cancelled":
            continue
            
        try:
            if pg_storage.mail_log_exists(order_id, "internal_order_received", "internal"):
                continue
                
            result = pg_storage.save_mail_log(
                event_order_id=order_id,
                direction="internal",
                template_key="internal_order_received",
                to_email="eventy@medidesk.com",
                subject="[IMPORT] Nowe zamówienie",
                data={"import_note": "Zaimportowane z Zoho Backstage"}
            )
            if result:
                mail_id = result.get("id")
                if mail_id:
                    pg_storage.mark_mail_sent(mail_id)
                success += 1
        except Exception as e:
            pass
    
    # Dodaj wpisy dla uczestników (participant_ticket)
    print(f"\n  --- Participant tickets ---")
    for att in ATTENDEES_DATA:
        order_id = att["order_id"]
        ticket_id = att["ticket_id"]
        contact = att.get("contact", {})
        email = contact.get("email", "")
        
        # Pomijamy not_attending
        if att.get("status_string") == "not_attending":
            continue
            
        try:
            # Sprawdź czy mail już istnieje dla tego uczestnika
            if pg_storage.mail_log_exists(order_id, "participant_ticket", "participant"):
                continue
                
            result = pg_storage.save_mail_log(
                event_order_id=order_id,
                direction="participant",
                template_key="participant_ticket",
                to_email=email,
                subject="[IMPORT] Bilet uczestnika",
                data={
                    "import_note": "Zaimportowane z Zoho Backstage - bilet już wysłany",
                    "ticket_id": ticket_id,
                }
            )
            if result:
                mail_id = result.get("id")
                if mail_id:
                    pg_storage.mark_mail_sent(mail_id)
                success += 1
        except Exception as e:
            pass
    
    print(f"\nMail log: {success} wpisów dodanych, {skipped} pominiętych")
    return success


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 60)
    print("JEDNORAZOWY IMPORT ZAMÓWIEŃ I UCZESTNIKÓW")
    print("=" * 60)
    
    if not os.getenv("DATABASE_URL"):
        print("\n[ERROR] Brak DATABASE_URL w środowisku!")
        print("Ustaw DATABASE_URL lub utwórz plik .env")
        sys.exit(1)
    
    # 1. Upewnij się, że event istnieje
    ensure_event_exists()
    
    # 2. Import zamówień
    orders_ok, orders_err = import_orders()
    
    # 3. Import uczestników z ATTENDEES_DATA
    att_ok, att_err = import_participants()
    
    # 4. Dodatkowo: import uczestników z biletów (dla kompletności)
    # Użycie ON CONFLICT oznacza, że duplikaty zostaną zaktualizowane
    tickets_ok, tickets_err = import_participants_from_tickets()
    
    # 5. WAŻNE: Oznacz maile jako wysłane (blokuje automatyczne wysyłki!)
    mail_logs_ok = mark_emails_as_sent()
    
    print("\n" + "=" * 60)
    print("PODSUMOWANIE")
    print("=" * 60)
    print(f"Zamówienia: {orders_ok} zaimportowanych")
    print(f"Uczestnicy (attendees): {att_ok} zaimportowanych")
    print(f"Uczestnicy (tickets): {tickets_ok} zaimportowanych")
    print(f"Mail log: {mail_logs_ok} wpisów (blokada auto-wysyłki)")
    
    total_errors = orders_err + att_err + tickets_err
    if total_errors > 0:
        print(f"\n[UWAGA] Wystąpiły błędy: {total_errors}")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Import zakończony pomyślnie!")


if __name__ == "__main__":
    main()
