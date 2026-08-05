# Nimbus Networks — Resolved Support Tickets (knowledge extract)

Curated from closed tickets. Each entry records symptom, root cause and the resolution that
actually worked, for reuse by support agents.

---
### TKT-10231 · Category: Connectivity · Resolved in 12 min
**Symptom:** Customer reports "no internet", INTERNET LED solid amber on RX-500.
**Root cause:** PPPoE password had been changed during a plan upgrade; router still had the old
one cached.
**Resolution:** Re-entered PPPoE credentials from the welcome email. Amber → green immediately.
**Note:** A hard reset is *not* needed for amber. Agents wasted time on resets before this was
documented.

---
### TKT-10488 · Category: Billing · Resolved in 3 days
**Symptom:** Customer charged ₹1,847 on a ₹899 plan and claimed billing error.
**Root cause:** Not an error — first invoice. ₹449 pro-rated + ₹899 next month + ₹499 remaining
installation balance.
**Resolution:** Explained first-invoice composition with a line-item breakdown. No refund issued.
**Note:** This is the single most common billing complaint. Lead with the breakdown, not policy.

---
### TKT-10502 · Category: Hardware · Resolved in 6 days
**Symptom:** RX-900 dead, POWER LED red, 4 days after delivery.
**Root cause:** Manufacturing defect.
**Resolution:** Treated as DOA (within 7 days) → advance replacement shipped same day, free
return label. Customer did not need to complete standard triage.

---
### TKT-10677 · Category: Wi-Fi · Resolved in 40 min
**Symptom:** Smart home devices (bulbs, plugs) repeatedly dropping off the network.
**Root cause:** IoT devices are 2.4 GHz only and were being pushed to 5 GHz by band steering,
combined with a DHCP pool of 50 already exhausted by 60+ devices.
**Resolution:** Disabled band steering, created a dedicated 2.4 GHz SSID, raised DHCP pool to
150 and cut lease time to 4 hours. Zero drops since.

---
### TKT-10715 · Category: Billing · Resolved in 1 day
**Symptom:** Account suspended despite customer having "paid".
**Root cause:** Auto-debit mandate expired; all three retry attempts failed silently because the
customer's email had the reminders in spam. Grace period lapsed.
**Resolution:** Payment collected manually, account restored within 15 min. Late fee of ₹50
waived as a goodwill gesture — agent discretion, one-time, logged in the account notes.

---
### TKT-10804 · Category: Hardware · Resolved in 21 days · ESCALATED
**Symptom:** RMA raised for faulty MX-2 mesh node, no replacement after 3 weeks.
**Root cause:** RMA was raised without triage notes and was rejected at the warehouse. Nobody
told the customer.
**Resolution:** Escalation policy applied — RMA exceeded 14 business days, so one month of free
service was credited and a replacement was expedited.
**Note:** Always attach triage notes to the RMA. Rejected RMAs do not notify the customer
automatically; this is a known gap in the RMA tool.

---
### TKT-10913 · Category: Connectivity · Resolved in 2 hours
**Symptom:** Business customer on Biz 300 reports intermittent drops, ~3 minutes every hour.
**Root cause:** Router firmware 4.1.8, below the 4.2.1 minimum. Auto-update had been disabled
by the customer's IT team.
**Resolution:** Manual firmware update to 4.3.0 over LAN. Drops stopped.

---
### TKT-11045 · Category: Refund · Resolved in 9 days
**Symptom:** Customer cancelled an annual plan after 5 months and expected a full refund of the
remaining 7 months.
**Root cause:** Expectation mismatch with the annual refund policy.
**Resolution:** Refunded 7 months pro-rata minus the 10% administrative charge. Customer accepted
once the calculation was shown explicitly.

---
### TKT-11190 · Category: Wi-Fi · Resolved in 25 min
**Symptom:** Customer cannot see the 5 GHz SSID on a new RX-900 in Bengaluru.
**Root cause:** Channel was set to auto and landed on UNII-3 (149-165), disabled on India units.
**Resolution:** Manually set 5 GHz channel to 44. SSID appeared instantly.
