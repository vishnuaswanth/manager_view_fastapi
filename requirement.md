# Requiremnts

## **Planning Phase:**

### Instructions
- I need you to create enpoints for the api spec provided. Refer @edit_view_api_spec.md
- Use DRY, SOLID principle for high quality code standards
- TRy to re-use already defined functions wherever possible
- Keep code clean and simple
- Use this function to get allocation reports data "get_available_report_months()"

- Make all traformation code look like pipeline operations.
- For /api/bench-allocation/update use /api/{change_type}/update : use same function same input format, only have to update relavent Forecast Data where the values got updated.

#### Bench allocation
- For Get Bench Allocation Preview - use allocate_bench_for_month() from code/logics/bench_allocation.py, then have function to transform data. The data transformation.

#### CPH Update
- get preview for cph update is triggered, for the given cph change, the lob and case type and report month and year - filter rows from forecast Data for the given report month and year and then by LOB and case type, after that modify the Target CPH value, because of which FTE Available and capacity values would vary for all months, so caculate them.

fte_req = forecast / (working_days * work_hours *(1-Shrinkage)* target_CPH). Round it to next positive integer

capacity = fte_avail * working_days * work_hours *(1-Shrinkage)* target_CPH

working_days, work_hours, Shrinkage all these are specific for different month and year, use month config data.

### History Log
- One table to record history log, which has log id , change type, report month, report year.
- Another table to track specific changes, where the history log id is used as foreign key and each change is a record in database.
    these are the specific data need to be stored
    {'main_lob': 'Amisys Medicaid DOMESTIC', 'state': 'LA', 'case_type': 'Claims Processing', 'case_id': 'CL-001', 'field': 'fte_avail', 'month': 'Jun-25', 'month_index': 'month1', 'old_value': 25.0, 'new_value': 28.0},
    For some fields that are not specific to any month month index should be made all like LOB, target CPH changes
create a function to transform the completed forecast data after allocation to traform into specific change, also for updating values through upload forecast find rows that were mofied and then transform it to specific changes. From all edit update request create trandform function to generate specific changes. In all forecast upload, update forecast or edit forecast data, say any data being updated to ForecastModel the changes have to be captured and history log created.
- Needs a single history log function like a interface function, same for all. Preprocessing can vary but after for all changes or creation the history log processing should be same for all.
- The chage types should be constant like enums should be used from one store. So that it can be easy to add or modify the change type in one instance
- Another table to store complete change data as json easily convertible from dataframe to json and then json to dataframe for excel export.
- history log download format for new and modified forecast values,
    - structure: Main LOB, State, Case Type, Case ID, Target CPH, May 2025, June 2025,... six months subject to wary according to report month and year. subheaders under Client Forecast, FTE Required, FTE Available, Capacity under each month like a pivot table. new values are displayed normally old value in within open brackets, this is only for updated values. When data is newly added no past data for reference for that report month and year no need of open brackets just values are enough