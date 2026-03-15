# Proposed GL classification for account_mappings (90 rows)

**Standard categories:**
- **P&L:** Revenue, Cost of Sales, Payroll & People Costs, Marketing & Sales, Technology & Infrastructure, Professional Fees, General & Administrative
- **BS:** Fixed Assets, Current Assets, Cash & Bank, Current Liabilities, Long-term Liabilities, Equity

| account_code | account_name | statement_type | reporting_category |
|--------------|--------------|----------------|---------------------|
| 090 | Business Bank Account | balance_sheet | Cash & Bank |
| 091 | Business Savings Account | balance_sheet | Cash & Bank |
| 200 | Sales | profit_and_loss | Revenue |
| 260 | Other Revenue | profit_and_loss | Revenue |
| 270 | Interest Income | profit_and_loss | Revenue |
| 300 | Purchases | profit_and_loss | Cost of Sales |
| 310 | Cost of Goods Sold | profit_and_loss | Cost of Sales |
| 320 | Direct Wages | profit_and_loss | Cost of Sales |
| 325 | Direct Expenses | profit_and_loss | Cost of Sales |
| 400 | Advertising & Marketing | profit_and_loss | Marketing & Sales |
| 401 | Audit & Accountancy fees | profit_and_loss | Professional Fees |
| 404 | Bank Fees | profit_and_loss | General & Administrative |
| 408 | Cleaning | profit_and_loss | General & Administrative |
| 412 | Consulting | profit_and_loss | Professional Fees |
| 416 | Depreciation Expense | profit_and_loss | General & Administrative |
| 418 | Charitable and Political Donations | profit_and_loss | General & Administrative |
| 420 | Entertainment-100% business | profit_and_loss | General & Administrative |
| 424 | Entertainment - 0% | profit_and_loss | General & Administrative |
| 425 | Postage, Freight & Courier | profit_and_loss | General & Administrative |
| 429 | General Expenses | profit_and_loss | General & Administrative |
| 433 | Insurance | profit_and_loss | General & Administrative |
| 437 | Interest Paid | profit_and_loss | General & Administrative |
| 441 | Legal Expenses | profit_and_loss | Professional Fees |
| 445 | Light, Power, Heating | profit_and_loss | Technology & Infrastructure |
| 449 | Motor Vehicle Expenses | profit_and_loss | General & Administrative |
| 457 | Operating Lease Payments | profit_and_loss | General & Administrative |
| 461 | Printing & Stationery | profit_and_loss | General & Administrative |
| 463 | IT Software and Consumables | profit_and_loss | Technology & Infrastructure |
| 465 | Rates | profit_and_loss | General & Administrative |
| 469 | Rent | profit_and_loss | General & Administrative |
| 473 | Repairs & Maintenance | profit_and_loss | General & Administrative |
| 477 | Salaries | profit_and_loss | Payroll & People Costs |
| 478 | Directors' Remuneration | profit_and_loss | Payroll & People Costs |
| 479 | Employers National Insurance | profit_and_loss | Payroll & People Costs |
| 480 | Staff Training | profit_and_loss | Payroll & People Costs |
| 482 | Pensions Costs | profit_and_loss | Payroll & People Costs |
| 483 | Medical Insurance | profit_and_loss | Payroll & People Costs |
| 485 | Subscriptions | profit_and_loss | General & Administrative |
| 489 | Telephone & Internet | profit_and_loss | Technology & Infrastructure |
| 493 | Travel - National | profit_and_loss | General & Administrative |
| 494 | Travel - International | profit_and_loss | General & Administrative |
| 497 | Bank Revaluations | profit_and_loss | General & Administrative |
| 498 | Unrealised Currency Gains | profit_and_loss | General & Administrative |
| 499 | Realised Currency Gains | profit_and_loss | General & Administrative |
| 500 | Corporation Tax | profit_and_loss | General & Administrative |
| 610 | Accounts Receivable | balance_sheet | Current Assets |
| 611 | Less Provision for Doubtful Debts | balance_sheet | Current Assets |
| 620 | Prepayments | balance_sheet | Current Assets |
| 630 | Inventory | balance_sheet | Current Assets |
| 710 | Office Equipment | balance_sheet | Fixed Assets |
| 711 | Less Accumulated Depreciation on Office Equipment | balance_sheet | Fixed Assets |
| 720 | Computer Equipment | balance_sheet | Fixed Assets |
| 721 | Less Accumulated Depreciation on Computer Equipment | balance_sheet | Fixed Assets |
| 740 | Buildings | balance_sheet | Fixed Assets |
| 741 | Less Accumulated Depreciation on Buildings | balance_sheet | Fixed Assets |
| 750 | Leasehold Improvements | balance_sheet | Fixed Assets |
| 751 | Less Accumulated Depreciation on Leasehold Improvements | balance_sheet | Fixed Assets |
| 760 | Motor Vehicles | balance_sheet | Fixed Assets |
| 761 | Less Accumulated Depreciation on Motor Vehicles | balance_sheet | Fixed Assets |
| 764 | Plant & Machinery | balance_sheet | Fixed Assets |
| 765 | Less Accumulated Depreciation on Plant and Machinery | balance_sheet | Fixed Assets |
| 770 | Intangibles | balance_sheet | Fixed Assets |
| 771 | Less Accumulated Amortisation on Intangibles | balance_sheet | Fixed Assets |
| 800 | Accounts Payable | balance_sheet | Current Liabilities |
| 801 | Unpaid Expense Claims | balance_sheet | Current Liabilities |
| 803 | Wage Payables | balance_sheet | Current Liabilities |
| 805 | Accruals | balance_sheet | Current Liabilities |
| 810 | Income in Advance | balance_sheet | Current Liabilities |
| 811 | Credit Card Control Account | balance_sheet | Current Liabilities |
| 814 | Wages Payable - Payroll | balance_sheet | Current Liabilities |
| 820 | VAT | balance_sheet | Current Liabilities |
| 825 | PAYE Payable | balance_sheet | Current Liabilities |
| 826 | NIC Payable | balance_sheet | Current Liabilities |
| 830 | Provision for Corporation Tax | balance_sheet | Current Liabilities |
| 835 | Directors' Loan Account | balance_sheet | Current Liabilities |
| 840 | Historical Adjustment | balance_sheet | Current Liabilities |
| 850 | Suspense | balance_sheet | Current Liabilities |
| 855 | Clearing Account | balance_sheet | Current Liabilities |
| 858 | Pensions Payable | balance_sheet | Current Liabilities |
| 860 | Rounding | balance_sheet | Current Liabilities |
| 868 | Earnings Orders Payable | balance_sheet | Current Liabilities |
| 877 | Tracking Transfers | balance_sheet | Current Liabilities |
| 900 | Loan | balance_sheet | Long-term Liabilities |
| 910 | Hire Purchase Loan | balance_sheet | Long-term Liabilities |
| 920 | Deferred Tax | balance_sheet | Long-term Liabilities |
| 947 | Student Loan Deductions Payable | balance_sheet | Current Liabilities |
| 950 | Capital - x,xxx Ordinary Shares | balance_sheet | Equity |
| 960 | Retained Earnings | balance_sheet | Equity |
| 970 | Owner A Funds Introduced | balance_sheet | Equity |
| 980 | Owner A Drawings | balance_sheet | Equity |
