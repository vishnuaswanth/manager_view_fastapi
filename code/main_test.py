from fastapi.testclient import TestClient
import io
from main import app,RosterModel
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import json


client = TestClient(app)



@pytest.mark.parametrize(
    "path, file_id, to_buffer_func, mime_type, file_name",
    [
        # ("roster", lambda df, buf: df.to_csv(buf, index=False), "text/csv", "csv"),
        (r'C:\Scripts\Python\CenteneForecasting\logics\data\Input\Centene Modified Roster-2.xlsm',"roster", lambda df, buf: df.to_excel(buf, index=False), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Centene Modified Roster-2 feb 2025.xlsx"),
        (r'C:\Scripts\Python\CenteneForecasting\logics\data\Input\NTT_Capacity Roster Template.xlsx',"roster_template", lambda df, buf: df.to_excel(buf, index=False), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "NTT_Capacity Roster Template feb 2025.xlsx"),
        (r'C:\Scripts\Python\CenteneForecasting\allocation_logic_backup\result.xlsx',"forecast", lambda df, buf: df.to_excel(buf, index=False), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "NTT Forecast - Capacity and HC - Feb 2025 V2.xlsx"),
    ]
)
def test_upload_roster(path, file_id, to_buffer_func, mime_type, file_name):
    if file_id == 'roster':
        df = pd.read_excel(path, sheet_name = "Roster", dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)
    buffer = io.BytesIO()
    to_buffer_func(df, buffer)
    buffer.seek(0)
    response = client.post(
        f"/upload/{file_id}", params={'user': 'Developer'},
        files={"file": (file_name, buffer, mime_type)}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "File uploaded and data saved."



def test_default():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["Success"] == "Centene forecasting default"

@pytest.mark.parametrize(
    "file_id, total, limit",
    [
        ("roster", 1598, 10),
        ("roster_template", 1694, 10),
        ("forecast", 318, 10),
    ]
)
def test_get_records_without_filter(file_id, total, limit):
    response = client.get(f"/records/{file_id}")
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == total  # 
    assert len(data['records']) == limit

@pytest.mark.parametrize(
    "file_id, total, reponse_count, header_fields",
    [
        ("roster", 1, 1, {"search": ["FD432071"], 'searchable_field':['OPID']}),
        ("roster_template", 1, 1, {"search": ["FD432071"], 'searchable_field':['OPID']}),
        ("forecast", 5, 5, {"search": ["ADJ MCARE"], 'searchable_field':['Centene_Capacity_Plan_Case_Type']}),
    ]
)

def test_get_records_with_search(file_id, total, reponse_count, header_fields):
    response = client.get(f"/records/{file_id}", params=header_fields)
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == total
    assert len(data['records']) == reponse_count
    assert data['records'][0][header_fields['searchable_field']] == header_fields['search']

@pytest.mark.parametrize(
    "file_id, total, reponse_count, header_fields, field_name",
    [
        ("roster", 1, 1, {"global_filter": "FD432071"}, "OPID"),
        ("roster_template", 1, 1, {"global_filter": "FD432071"}, "OPID"),
        ("forecast", 5, 5, {"global_filter": "ADJ MCARE"}, "Centene_Capacity_Plan_Case_Type"),
    ]
)
def test_get_records_with_global_filter(file_id, total, reponse_count, header_fields, field_name):
    response = client.get(f"/records/{file_id}", params=header_fields)
    assert response.status_code == 200
    data = response.json()
    print(data)
    assert data['total'] == total
    assert len(data['records']) == reponse_count
    assert data['records'][0][field_name] == header_fields['global_filter']

@pytest.mark.parametrize("endpoint", [
    ('records'), 
    ('record_history')
])
def test_for_invalid_model(endpoint):
    response = client.get(f"/{endpoint}/invalid_model")
    assert response.status_code == 404
    assert response.json() == {"detail": "Model not found"}

@pytest.mark.parametrize("file_id, skip, limit, expected_count, total", [
    ('roster',0, 1, 1,1598),  # Should return 1 when skip is 0 and limit is 1
    ('roster',1, 1, 1, 1598),  # Should return the next record when skip is 1 and limit is 1
    ('roster',1598, 10, 0, 1598),  # Skip all records and expect 0
    ('roster_template',0, 1, 1, 1694),  # Should return 1 when skip is 0 and limit is 1
    ('roster_template',1, 1, 1, 1694),  # Should return the next record when skip is 1 and limit is 1
    ('roster_template',1694, 10, 0, 1694),  # Skip all records and expect 0
    ('forecast',0, 1, 1, 318),  # Should return 1 when skip is 0 and limit is 1
    ('forecast',1, 1, 1, 318),  # Should return the next record when skip is 1 and limit is 1
    ('forecast',318, 10, 0, 318),  # Skip all records and expect 0
])
def test_get_records_with_pagination(file_id, skip, limit, expected_count, total):
    response = client.get(f"/records/{file_id}?skip={skip}&limit={limit}")
    assert response.status_code == 200
    data = response.json()
    assert data['total'] ==  total # Total records should remain the same
    assert len(data['records']) == expected_count

@pytest.mark.parametrize("model", [
    ('roster'), 
    ('roster_template'),
    ('forecast')
])

def test_get_records_history(model):
    response = client.get(f"/record_history/{model}")
    assert response.status_code == 200
    data = response.json()
    assert data['total'] ==  1 # Total records should remain the same
    assert len(data['records']) == 1



def test_get_model_schema_forecast():
    response = client.get("/model_schema/forecast")
    assert response.status_code == 200
    result = response.json()
    assert "tab" in result
    assert "data" in result
    months = {v for k, v in result["tab"]["records"][0].items() if k not in {'CreatedBy', 'id', 'CreatedDateTime', 'UploadedFile'}}
    assert  months == {'March','April','May','June','July','August'}
    assert result["data"]["total"] == 318
    assert result["data"]["records"][0]["UploadedFile"] == "NTT Forecast - Capacity and HC - Feb 2025 V2.xlsx"


def test_get_model_schema_not_found():
    response = client.get("/model_schema/unknown")
    assert response.status_code == 404
    assert response.json() == {"detail": "Model not found"}

@pytest.mark.parametrize(
    "path, file_id",
    [
        # ("roster", lambda df, buf: df.to_csv(buf, index=False), "text/csv", "csv"),
        (r'C:\Scripts\Python\CenteneForecasting\logics\data\Input\Centene Modified Roster-2.xlsm',"roster"),
        (r'C:\Scripts\Python\CenteneForecasting\logics\data\Input\NTT_Capacity Roster Template.xlsx',"roster_template"),
        (r'C:\Scripts\Python\CenteneForecasting\allocation_logic_backup\result.xlsx',"forecast"),
    ]
)
def test_excel_download(path, file_id):
    # Send POST request
    response = client.post(f"/download_file/{file_id}")
    
    # Check response status
    assert response.status_code == 200
    assert response.headers['content-type'] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    # Read the Excel file from response
    output = io.BytesIO(response.content)
    df = pd.read_excel(output)
    
    # Check DataFrame content
    expected_df = pd.read_csv(path)
    pd.testing.assert_frame_equal(df, expected_df)

def test_excel_download():
    response = client.get("/download_file/unknown")
    assert response.status_code == 404
    assert response.json() == {"detail": "Model not found"}