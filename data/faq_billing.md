# Nimbus Networks — Billing & Accounts FAQ

## When is my bill generated?
Invoices are generated on the 1st of every month and cover the *previous* month of service.
Payment is due 14 days after generation. A payment reminder email is sent on day 10 and day 13.

## What payment methods do you accept?
Credit/debit card (Visa, Mastercard, Amex), UPI, net banking, and auto-debit mandates (eNACH).
We do not accept cash, cheque, or cryptocurrency.

## What happens if my payment fails?
1. We retry the charge automatically after 24 hours, then again after 72 hours.
2. If all three attempts fail, the account moves to **Grace** status for 7 days. Service continues.
3. After the grace period the account moves to **Suspended**. Inbound service stops; the account
   is retained for 30 days.
4. After 30 days suspended, the account is **Terminated** and the assigned static IP is released.

A late fee of 2% of the outstanding amount (minimum ₹50, maximum ₹500) is applied once the
account enters Suspended status. Late fees are not applied during the grace period.

## How do I get a GST invoice?
Add your GSTIN under Account → Billing Profile before the 25th of the month. Invoices generated
after that date will carry the GSTIN. We cannot reissue past invoices with a new GSTIN — this is
a statutory restriction, not a policy choice.

## Can I change my billing cycle date?
Yes, once per calendar year. Account → Billing → Change Cycle. The change takes effect from the
next invoice and generates one pro-rated invoice for the transition period.

## Why is my first bill higher than my plan price?
The first invoice includes: (a) pro-rated charges from activation date to the end of that month,
(b) the full next month in advance, and (c) any one-time installation fee. This is normal.

## How do I cancel my subscription?
Account → Plan → Cancel Subscription, or contact support. Cancellation takes effect at the end of
the current billing period. We do not pro-rate refunds for partial months on monthly plans.
Annual plans are refunded pro-rata minus a 10% administrative charge.

## Do you offer refunds for downtime?
Yes. If measured uptime in a calendar month falls below the SLA for your plan, an automatic
service credit is applied to the next invoice. See the Service Level section of the product
catalog for per-plan SLA numbers. Credits are applied automatically — no ticket needed.
