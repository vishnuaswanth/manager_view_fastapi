
from typing import List, Dict, Optional, Type, Union

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    and_,
    inspect,
    extract,
    func,
    case,
    or_,
    Index,
    true,
    literal_column,
    UniqueConstraint
)

from sqlalchemy.orm import sessionmaker, declarative_base, aliased

from sqlmodel import Session, select, SQLModel, create_engine, Field, Column, TIMESTAMP, text
from pydantic import Field as PyField
from datetime import datetime
import pandas as pd
import typing
from sqlalchemy import Column, DateTime
from collections import OrderedDict
from calendar import month_name, month_abbr
from sqlalchemy.exc import SQLAlchemyError

import logging
from code.logics.types import DataFrameJSON
from code.logics.cache_utils import TTLCache
# from code.settings import setup_logging

# setup_logging()

logger = logging.getLogger(__name__)

# Cache for get_distinct_values() queries to avoid redundant DB queries
# Example: When cascading through filters, Main_LOB query is reused across 4 endpoints
# TTL: 5 minutes (same as filters_cache), Max: 50 entries
_distinct_values_cache = TTLCache(max_size=50, ttl_seconds=300)


def normalize_month(month_str):
    """Convert month string to capitalized full month name."""
    month_str = month_str.strip().lower()
    # Try full month names
    for i in range(1, 13):
        if month_str == month_name[i].lower():
            return month_name[i]
    # Try abbreviated month names
    for i in range(1, 13):
        if month_str == month_abbr[i].lower():
            return month_name[i]
    raise ValueError(f"Invalid month string: {month_str}")

# In db.py

# class MonthData(SQLModel, table=True):
#     id: int | None = Field(default=None, primary_key=True)

#     month: Optional[str]
#     no_of_days_occupancy: Optional[int]
#     occcupancy: Optional[float]
#     shrinkage: Optional[float]
#     work_hours: Optional[int]


# class TargetCPH(SQLModel, table=True):
#     id: int | None = Field(default=None, primary_key=True)

#     main_lob: Optional[str]
#     case_type:
#     Target CPH


class UploadDataTimeDetails(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    Month: str
    Year: int


class SkillingModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    Position: Optional[str]
    FirstName: Optional[str]
    LastName: Optional[str]
    PortalId: Optional[str]
    Status: Optional[str]
    Resource_Status: Optional[str]
    LOB_1: Optional[str]
    Sub_LOB: Optional[str]
    Site: Optional[str]
    Skills: Optional[str]
    State: Optional[str]
    Unique_Agent: Optional[int]
    Multi_Skill: Optional[int]
    Skill_Name: Optional[str]
    Skill_Split: Optional[float]

    Month: str
    Year: int
    UploadedFile: str
    CreatedBy: str
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    UpdatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
    UpdatedBy: str


class RosterModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    Platform: Optional[str]
    WorkType: Optional[str]
    State: Optional[str]
    Product: Optional[str]
    Location: Optional[str]
    ResourceStatus: Optional[str]
    Status: Optional[str]
    FirstName: Optional[str]
    LastName: Optional[str]
    PortalId: Optional[str]
    CN: Optional[str]
    WorkdayId: Optional[str]
    HireDate_AmisysStartDate: Optional[str]
    OPID: Optional[str]
    Position: Optional[str]
    TL: Optional[str]
    Supervisor: Optional[str]
    PrimarySkills: Optional[str]
    SecondarySkills: Optional[str]
    City: Optional[str]
    ClassName: Optional[str]
    FTC_START_TRAINING: Optional[str]
    FTC_END_TRAINING: Optional[str]
    ADJ_COB_START_TRAINING: Optional[str]
    ADJ_COB_END_TRAINING: Optional[str]
    CourseType: Optional[str]
    BH: Optional[str]
    SplProj: Optional[str]
    DualPends: Optional[str]
    RampStartDate: Optional[str]
    RampEndDate: Optional[str]
    Ramp: Optional[str]
    CPH: Optional[str]
    CrossTrainedTrainingDate: Optional[str]
    CrossTrainedProdDate: Optional[str]
    ProductionStartDate: Optional[str]
    Facilitator_Cofacilitator: Optional[str]
    Centene_WellCareEmail: Optional[str]
    Additional_Email_NTT: Optional[str]
    Month: str
    Year: int
    UploadedFile:str
    CreatedBy: str
    CreatedDateTime: datetime = Field(
    sa_column=Column(DateTime, nullable=False, server_default=func.now())
        )
    UpdatedDateTime: datetime = Field(
            sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
        )
    UpdatedBy:str


class RosterTemplate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    FirstName: Optional[str]
    LastName : Optional[str]
    CN : Optional[str]
    OPID: Optional[str]
    Location : Optional[str]
    ZIPCode: Optional[str]
    City: Optional[str]
    BeelineTitle: Optional[str]
    Status: Optional[str]
    PrimaryPlatform: Optional[str]
    PrimaryMarket: Optional[str]
    Worktype: Optional[str]
    LOB: Optional[str]
    SupervisorFullName : Optional[str]
    SupervisorCNNo: Optional[str]
    UserStatus: Optional[str]
    PartofProduction: Optional[str]
    ProductionPercentage : Optional[str]
    NewWorkType : Optional[str]
    State : Optional[str]
    CenteneMailId: Optional[str]
    NTTMailID: Optional[str]
    Month: str
    Year: int
    UploadedFile:str
    CreatedBy: str
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    UpdatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
    UpdatedBy:str

class ProdTeamRosterModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    FirstName: Optional[str]
    LastName: Optional[str]
    CN: Optional[str]
    OPID: Optional[str]
    Location: Optional[str]
    ZIPCode: Optional[str]
    City: Optional[str]
    BeelineTitle: Optional[str]
    Status: Optional[str]
    PrimaryPlatform: Optional[str]
    PrimaryMarket: Optional[str]
    Worktype: Optional[str]
    LOB: Optional[str]
    SupervisorFullName: Optional[str]
    SupervisorCNNo: Optional[str]
    UserStatus: Optional[str]
    PartofProduction: Optional[str]
    ProductionPercentage: Optional[float]
    NewWorkType: Optional[str]
    State: Optional[str]
    CenteneMailId: Optional[str]
    NTTMailID: Optional[str]

    UploadedFile: str
    CreatedBy: str
    UpdatedBy: str
    Month: Optional[str]
    Year: Optional[int]
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), nullable=False)
    )
    UpdatedDateTime: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class ForecastModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    Centene_Capacity_Plan_Main_LOB: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True)
    )
    Centene_Capacity_Plan_State: Optional[str] = Field(
        default=None,
        sa_column=Column(String(100), nullable=True)
    )
    Centene_Capacity_Plan_Case_Type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True)
    )
    Centene_Capacity_Plan_Call_Type_ID : Optional[str]
    Centene_Capacity_Plan_Target_CPH :Optional[int]
    Client_Forecast_Month1 :Optional[int]
    Client_Forecast_Month2 :Optional[int]
    Client_Forecast_Month3 :Optional[int]
    Client_Forecast_Month4 :Optional[int]
    Client_Forecast_Month5 :Optional[int]
    Client_Forecast_Month6 :Optional[int]
    FTE_Required_Month1 :Optional[int]
    FTE_Required_Month2 :Optional[int]
    FTE_Required_Month3 :Optional[int]
    FTE_Required_Month4 :Optional[int]
    FTE_Required_Month5 :Optional[int]
    FTE_Required_Month6 :Optional[int]
    FTE_Avail_Month1 :Optional[int]
    FTE_Avail_Month2 :Optional[int]
    FTE_Avail_Month3 :Optional[int]
    FTE_Avail_Month4 :Optional[int]
    FTE_Avail_Month5 :Optional[int]
    FTE_Avail_Month6 :Optional[int]
    Capacity_Month1 :Optional[int]
    Capacity_Month2 :Optional[int]
    Capacity_Month3 :Optional[int]
    Capacity_Month4 :Optional[int]
    Capacity_Month5 :Optional[int]
    Capacity_Month6 :Optional[int]
    Month: str = Field(sa_column=Column(String(15), nullable=False))  # Max length: "September" = 9 chars
    Year: int
    UploadedFile: str = Field(sa_column=Column(String(255), nullable=False))
    CreatedBy: str = Field(sa_column=Column(String(100), nullable=False))
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    UpdatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
    UpdatedBy: str = Field(sa_column=Column(String(100), nullable=False))

    # Indexes for cascade filter performance
    __table_args__ = (
        Index('idx_forecast_year_month', 'Year', 'Month'),
        Index('idx_forecast_main_lob', 'Centene_Capacity_Plan_Main_LOB'),
        Index('idx_forecast_case_type', 'Centene_Capacity_Plan_Case_Type'),
    )

class ForecastMonthsModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    Month1: str = Field(sa_column=Column(String(15), nullable=False))
    Month2: str = Field(sa_column=Column(String(15), nullable=False))
    Month3: str = Field(sa_column=Column(String(15), nullable=False))
    Month4: str = Field(sa_column=Column(String(15), nullable=False))
    Month5: str = Field(sa_column=Column(String(15), nullable=False))
    Month6: str = Field(sa_column=Column(String(15), nullable=False))
    UploadedFile: str = Field(sa_column=Column(String(255), nullable=False))
    CreatedBy: str = Field(sa_column=Column(String(100), nullable=False))
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )

class AllocationReportsModel(SQLModel, table=True):
    """
    Model for storing allocation reports (bucket summary, bucket after allocation, roster allotment).
    For each (Month, Year, ReportType) combination, only the latest report is stored.
    """
    id: int | None = Field(default=None, primary_key=True)
    Month: str = Field(sa_column=Column(String(15), nullable=False))
    Year: int = Field(nullable=False)
    ReportType: str = Field(sa_column=Column(String(50), nullable=False))  # 'bucket_summary', 'bucket_after_allocation', 'roster_allotment'
    ReportData: str = Field(sa_column=Column(Text, nullable=False))  # JSON string of DataFrame
    CreatedBy: str = Field(sa_column=Column(String(100), nullable=False))
    CreatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    UpdatedDateTime: datetime = Field(
        sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
    UpdatedBy: str = Field(sa_column=Column(String(100), nullable=False))

    # UniqueConstraint ensures only one report per (Month, Year, ReportType)
    __table_args__ = (
        UniqueConstraint('Month', 'Year', 'ReportType', name='uix_allocation_report'),
        Index('idx_allocation_month_year', 'Month', 'Year'),
    )

class RawData(SQLModel, table=True):
    __tablename__ = "raw_data"

    id: int = Field(default=None, primary_key=True)
    data_model: str = Field(
        sa_column=Column(String(100), nullable=False)  # <= fixed length to allow indexing
    )
    data_model_type: str = Field(
        sa_column=Column(String(100), nullable=False)  # <= fixed length to allow indexing
    )
    month: str = Field(
        sa_column=Column(String(15), nullable=False)  # <= fixed length to allow indexing
    )
    year: int = Field(nullable=False)
    version: int = Field(default=1, nullable=False)  # NEW: version tracking
    is_current: bool = Field(default=True, nullable=False)  # NEW: current version flag

    dataframe_json: pd.DataFrame = Field(
        sa_column=Column(DataFrameJSON, nullable=False)
    )

    created_by: str = Field(nullable=False)
    updated_by: str = Field(default=None)

    created_on: datetime = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    updated_on: datetime = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )

    # Add indexes for faster queries
    __table_args__ = (
        Index('idx_data_current','data_model', 'data_model_type', 'month', 'year', 'is_current'),
        Index('idx_data_version','data_model', 'data_model_type', 'month', 'year', 'version'),
    )

    model_config = {
        "arbitrary_types_allowed": True
    }


class InValidSearchException(Exception):
    """Exception raised for custom error scenarios.

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

def tuple_to_dict(row, columns):
    return dict(zip([col.key if hasattr(col, 'key') else str(col) for col in columns], row))

class DBManager:
    def __init__(self, database_url: str, Model,limit:int, skip:int, select_columns:List[str]):
        """
        Initialize the DBManager with a database URL.

        Args:
            database_url (str): The database connection string.
        """
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.Model = Model
        self.skip = skip
        self.limit = limit
        if select_columns:
            self.select_columns = [getattr(Model, col_name) for col_name in select_columns]
        else:
            self.select_columns = None

        self.METRIC_COLUMNS: List[str] = [
            "Client_Forecast_Month1", "Client_Forecast_Month2", "Client_Forecast_Month3",
            "Client_Forecast_Month4", "Client_Forecast_Month5", "Client_Forecast_Month6",
            "FTE_Required_Month1", "FTE_Required_Month2", "FTE_Required_Month3",
            "FTE_Required_Month4", "FTE_Required_Month5", "FTE_Required_Month6",
            "FTE_Avail_Month1", "FTE_Avail_Month2", "FTE_Avail_Month3",
            "FTE_Avail_Month4", "FTE_Avail_Month5", "FTE_Avail_Month6",
            "Capacity_Month1", "Capacity_Month2", "Capacity_Month3",
            "Capacity_Month4", "Capacity_Month5", "Capacity_Month6",
        ]

    @staticmethod
    def _zero_metrics_dict() -> Dict[str, int]:
        """Fast zeroed result with the exact shape you expect."""
        return {
            "Client_Forecast_Month1": 0, "Client_Forecast_Month2": 0, "Client_Forecast_Month3": 0,
            "Client_Forecast_Month4": 0, "Client_Forecast_Month5": 0, "Client_Forecast_Month6": 0,
            "FTE_Required_Month1": 0, "FTE_Required_Month2": 0, "FTE_Required_Month3": 0,
            "FTE_Required_Month4": 0, "FTE_Required_Month5": 0, "FTE_Required_Month6": 0,
            "FTE_Avail_Month1": 0, "FTE_Avail_Month2": 0, "FTE_Avail_Month3": 0,
            "FTE_Avail_Month4": 0, "FTE_Avail_Month5": 0, "FTE_Avail_Month6": 0,
            "Capacity_Month1": 0, "Capacity_Month2": 0, "Capacity_Month3": 0,
            "Capacity_Month4": 0, "Capacity_Month5": 0, "Capacity_Month6": 0,
        }

    def filter_by_month_and_year(self, query, month_str: str, year: int):
        """
        Filter Event table by month and year.

        Args:
            session (Session): SQLAlchemy session.
            month_str (str): Month as string (e.g., 'January', 'Jan', 'jan').
            year (int): Year as integer (e.g., 2024).

        Returns:
            List[Event]: List of matching Event objects.
        """
        normalized_month = normalize_month(month_str)
        results = query.filter(
            self.Model.Month == normalized_month,
            self.Model.Year == year
        )
        # Month-Year based filtering using max(CreatedDateTime, UpdatedDateTime)
            # if month and year:

            #     Created = getattr(self.Model, "CreatedDateTime")
            #     Updated = getattr(self.Model, "UpdatedDateTime")

            #     effective_date = case(
            #         (Created > Updated, Created),
            #         else_=Updated
            #     ).label("effective_date")

            #     query = query.filter(
            #         extract('month', effective_date) == month,
            #         extract('year', effective_date) == year
            #     )
        return results

    def _execute_query(self, query):

        if self.select_columns:
            records = query.with_entities(*self.select_columns).distinct().all()
            records = [tuple_to_dict(row, self.select_columns) for row in records]
            total = len(records)
            records = records[self.skip:self.skip+self.limit]
        else:
            total = query.count()
            query = query.order_by(self.Model.id)
            records = query.offset(self.skip).limit(self.limit)
            records = records.all()
            record_dicts = [OrderedDict((column.name, getattr(row, column.name)) for column in row.__table__.columns) for row in records]

            records = record_dicts
        return {"total": total, "records": records}

    def save_to_db(self, df: pd.DataFrame, replace: bool = False):
        """
        Save DataFrame to DB using SQLAlchemy ORM.
        If `replace=True`, delete existing records with matching (Month, Year).
        Rolls back on failure and logs exception.
        """
        session = self.SessionLocal()

        try:
            # Step 1: delete existing rows if needed
            if replace and "Month" in df.columns and "Year" in df.columns:

                month = df["Month"].iloc[0].strip().capitalize()
                year = int(df["Year"].iloc[0])

                # month = df["Month"].iloc[0]
                # year = df["Year"].iloc[0]

                logger.info(f"[DBManager] Replacing rows for {month} {year}")
                delete_query = session.query(self.Model).filter(
                    and_(
                        func.lower(func.trim(self.Model.Month)) == month.lower(),
                        self.Model.Year == year  # Ensure matching type
                    )
                )
                matched = delete_query.count()
                logger.info(f"[DBManager] Found {matched} records to delete...")
                deleted_count = delete_query.delete(synchronize_session=False)
                logger.info(f"[DBManager] Deleted {deleted_count} existing records.")

            # Step 2: insert new records
            records = df.to_dict(orient="records")
            instances = [self.Model(**row) for row in records]
            session.add_all(instances)
            session.commit()
            logger.info(f"[DBManager] Inserted {len(instances)} new records.")

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"[DBManager] Error during save_to_db. Rolled back. Error: {e}")
            raise Exception(f"Error saving to database: {str(e)}") from e

        finally:
            session.close()
            logger.debug("[DBManager] Session closed.")

    def bulk_save_raw_data_with_history(
        self,
        bulk_data: List[Dict],  # List of {df, summary_type, month, year, created_by, updated_by}
        retain_history: bool = True,
        max_versions: int = 5  # Keep only last 5 versions
    ):
        """
        Bulk insert/update summaries with history retention.

        Args:
            summary_data: List of dictionaries containing:
                - df: pandas DataFrame
                - data_model: str
                - data_model_type: str
                - month: str
                - year: int
                - created_by: str
                - updated_by: str (optional)
            retain_history: If True, keeps old versions; if False, replaces
            max_versions: Maximum versions to retain per (summary_type, month, year)
        """
        session = self.SessionLocal()
        Model = RawData

        try:
            for data in bulk_data:
                df = data['df']
                data_model = data['data_model']
                data_model_type = data['data_model_type']
                month = data['month']
                year = data['year']
                created_by = data['created_by']
                updated_by = data.get('updated_by', created_by)

                if retain_history:
                    # Mark existing current record as historical
                    session.query(Model).filter(
                        and_(
                            Model.data_model == data_model,
                            Model.data_model_type == data_model_type,
                            Model.month == month,
                            Model.year == year,
                            Model.is_current == True
                        )
                    ).update({Model.is_current: False})

                    # Get next version number
                    max_version = session.query(func.max(Model.version)).filter(
                        and_(
                            Model.data_model == data_model,
                            Model.data_model_type == data_model_type,
                            Model.month == month,
                            Model.year == year
                        )
                    ).scalar() or 0

                    next_version = max_version + 1

                    # Clean up old versions if exceeding max_versions
                    if max_versions > 0:
                        old_versions = session.query(Model).filter(
                            and_(
                                Model.data_model == data_model,
                                Model.data_model_type == data_model_type,
                                Model.month == month,
                                Model.year == year,
                                Model.is_current == False
                            )
                        ).order_by(Model.version.desc()).offset(max_versions - 1).all()

                        for old_record in old_versions:
                            session.delete(old_record)

                else:
                    # Delete all existing records (no history)
                    session.query(Model).filter(
                        and_(
                            Model.data_model == data_model,
                            Model.data_model_type == data_model_type,
                            Model.month == month,
                            Model.year == year
                        )
                    ).delete(synchronize_session=False)
                    next_version = 1

                # Create new record
                record = Model(
                    data_model=data_model,
                    data_model_type=data_model_type,
                    month=month,
                    year=year,
                    version=next_version,
                    is_current=True,
                    dataframe_json=df,
                    created_by=created_by,
                    updated_by=updated_by,
                )
                session.add(record)

                logger.info(f"[DBManager] Added raw data v{next_version} for ({data_model},{data_model_type}, {month}, {year})")

            session.commit()
            logger.info(f"[DBManager] Bulk saved {len(bulk_data)} raw data")

        except Exception as e:
            session.rollback()
            logger.error(f"[DBManager] Error in bulk save: {e}")
            raise
        finally:
            session.close()


    def get_raw_data_df_current(
        self,
        data_model: str,
        data_model_type: str,
        month: str,
        year: int
    ) -> pd.DataFrame:
        """
        Retrieve current (latest) DataFrame from Raw Data.
        """
        session = self.SessionLocal()
        Model = RawData

        try:
            record = session.query(Model).filter(
                and_(
                    Model.data_model == data_model,
                    Model.data_model_type == data_model_type,
                    Model.month == month,
                    Model.year == year,
                    Model.is_current == True
                )
            ).first()

            if record:
                logger.info(f"[DBManager] Retrieved current raw data v{record.version} for ({data_model}, {data_model_type}, {month}, {year})")
                return record.dataframe_json  # Auto-deserialized by DataFrameJSON
            else:
                logger.info(f"[DBManager] No current raw data found for ({data_model}, {data_model_type}, {month}, {year})")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"[DBManager] Error retrieving current raw data: {e}")
            raise
        finally:
            session.close()

    def get_raw_data_df_by_version(
        self,
        data_model: str,
        data_model_type: str,
        month: str,
        year: int,
        version: int
    ) -> pd.DataFrame:
        """Retrieve specific version of DataFrame."""
        session = self.SessionLocal()
        Model = RawData

        try:
            record = session.query(Model).filter(
                and_(
                    Model.data_model == data_model,
                    Model.data_model_type == data_model_type,
                    Model.month == month,
                    Model.year == year,
                    Model.version == version
                )
            ).first()

            if record:
                logger.info(f"[DBManager] Retrieved raw data v{version} for ({data_model}, {data_model_type}, {month}, {year})")
                return record.dataframe_json
            else:
                logger.info(f"[DBManager] No raw data v{version} found for ({data_model}, {data_model_type}, {month}, {year})")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"[DBManager] Error retrieving raw data v{version}: {e}")
            raise
        finally:
            session.close()

    def get_all_current_data_models_of_raw_data(
        self,
        data_model: str,
        month:str=None,
        year:int=None,
    ) -> List[RawData]:
        """Get all current raw for a specific month and year and data_model or latest data from given data_model"""
        session = self.SessionLocal()
        Model = RawData


        month_num = case(
            (Model.month == 'January', 1),
            (Model.month == 'February', 2),
            (Model.month == 'March', 3),
            (Model.month == 'April', 4),
            (Model.month == 'May', 5),
            (Model.month == 'June', 6),
            (Model.month == 'July', 7),
            (Model.month == 'August', 8),
            (Model.month == 'September', 9),
            (Model.month == 'October', 10),
            (Model.month == 'November', 11),
            (Model.month == 'December', 12),
            else_=0
        )

        try:
            if month and year:
                subq = (
                    select(
                        Model.id,
                        func.row_number().over(
                            partition_by=Model.data_model_type,
                            order_by=Model.data_model_type.asc()  # or whatever "latest" order you want
                        ).label("rn")
                    )
                    .where(
                        Model.data_model == data_model,
                        Model.month == month,
                        Model.year == year,
                        Model.is_current == true()
                    )
                ).subquery()
            else:
                subq = (
                    select(
                        Model.id,
                        func.row_number().over(
                            partition_by=Model.data_model_type,
                            order_by=[Model.year.desc(), month_num.desc()]
                        ).label("rn")
                    )
                    .where(
                        Model.data_model == data_model,
                        Model.is_current == true()
                    )
                ).subquery()


            m_alias = aliased(Model)

            stmt = (
                select(m_alias)
                .join(subq, subq.c.id == m_alias.id)
                .where(subq.c.rn == 1)
                .order_by(m_alias.data_model_type.asc())
            )
            records = list(session.execute(stmt).scalars().all())
            # records = session.query(Model).filter(
            if records and len(records)>0:
                logger.info(f"[DBManager] Retrieved {len(records)} current raw data for ({data_model}, {month}, {year})")
                return records
            else:
                logger.info(f"[DBManager] No current raw data found for ({data_model}, {month}, {year})")
                return []
        except Exception as e:
            logger.error(f"[DBManager] Error retrieving current raw data: {e}")
            raise
        finally:
            session.close()

    def get_raw_data_history(
        self,
        data_model: str,
        data_model_type: str,
        month: str,
        year: int
    ) -> List[Dict]:
        """Get version history metadata (no DataFrame data)."""
        session = self.SessionLocal()
        Model = RawData

        try:
            records = session.query(
                Model.version,
                Model.is_current,
                Model.created_by,
                Model.updated_by,
                Model.created_on,
                Model.updated_on
            ).filter(
                and_(
                    Model.data_model == data_model,
                    Model.data_model_type == data_model_type,
                    Model.month == month,
                    Model.year == year
                )
            ).order_by(Model.version.desc()).all()

            history = [
                {
                    'version': r.version,
                    'is_current': r.is_current,
                    'created_by': r.created_by,
                    'updated_by': r.updated_by,
                    'created_on': r.created_on,
                    'updated_on': r.updated_on
                }
                for r in records
            ]

            logger.info(f"[DBManager] Retrieved {len(history)} versions for ({data_model}, {data_model_type}, {month}, {year})")
            return history

        except Exception as e:
            logger.error(f"[DBManager] Error retrieving raw data history: {e}")
            raise
        finally:
            session.close()


    def search_db(self, searchable_fields:List[str], keywords:List[str], month: str = None, year: int = None):
        if not searchable_fields and not (month and year):
            raise InValidSearchException('Column based seach is called but searchable_fields are empty or Month data is missing')
        with self.SessionLocal() as session:
            query = session.query(self.Model)
            if month and year:
                query=self.filter_by_month_and_year(query, month, year)

            # if searchable_field and keyword:
            #     query = query.filter(getattr(self.Model, searchable_field).contains(keyword))

            if searchable_fields and keywords:

                # filters = [
                #     getattr(self.Model, field).contains(keyword)
                #     for field in searchable_fields
                #     for keyword in keywords
                # ]
                # query = query.filter(or_(*filters))

                filters = [
                    or_(*[getattr(self.Model, field).ilike(f"%{keyword}%") for field in searchable_fields])
                    for keyword in keywords
                ]

                query = query.filter(and_(*filters))

            return self._execute_query(query)

    def global_search_db(self, keyword, month:str=None, year:int =None):
        with self.SessionLocal() as session:
            query = session.query(self.Model)
            if month or year:
                query = self.filter_by_month_and_year(query, month, year)
            columns = []

            for key, value in typing.get_type_hints(self.Model).items():
                if value==str or Optional[str]:
                    columns.append(key)
            for c in ['__tablename__', '__sqlmodel_relationships__', '__name__', 'metadata']:
                columns.remove(c)

            if len(columns)<1:
                raise InValidSearchException(f'Data model does not have sufficent columns to search{str([str(c) for c in columns])}')
            conditions = [getattr(self.Model, column).contains(keyword) for column in columns]
            query = query.filter(or_(*conditions))
            return self._execute_query(query)

    def read_db(self, month=None, year=None):
        with self.SessionLocal() as session:
            query = session.query(self.Model)
            if month and year:
                query=self.filter_by_month_and_year(query, month, year)
            return self._execute_query(query)

    def get_distinct_values(
        self,
        column_name: str,
        month: Optional[str] = None,
        year: Optional[int] = None,
        filter_values: Optional[Dict[str, List[str]]] = None
    ) -> List[str]:
        """
        Get distinct non-null values for a column using optimized database query.
        Database-agnostic: works with both SQLite and MSSQL.

        **Internal Caching**: Results are cached for 5 minutes to avoid redundant queries.
        Example: When cascading filters, Main_LOB query is reused across platforms/markets/localities/worktypes.

        Args:
            column_name: Column to get distinct values from (e.g., 'Year', 'Centene_Capacity_Plan_Main_LOB')
            month: Optional month filter (full name like "February")
            year: Optional year filter
            filter_values: Optional dict of {column_name: [allowed_values]} for additional filtering
                          Example: {"Centene_Capacity_Plan_Main_LOB": ["Amisys Medicaid", "Facets Medicare"]}
                          Used for worktype endpoint to filter Case_Type by matching Main_LOBs

        Returns:
            Sorted list of distinct values (None/empty excluded)

        Example:
            # Get all years
            >>> db_manager.get_distinct_values("Year")
            [2023, 2024, 2025]

            # Get distinct Main_LOB for February 2025
            >>> db_manager.get_distinct_values("Centene_Capacity_Plan_Main_LOB", "February", 2025)
            ['Amisys Medicaid Domestic', 'Facets Medicare', ...]

            # Get distinct Case_Type WHERE Main_LOB IN [matching_lobs]
            >>> db_manager.get_distinct_values(
                "Centene_Capacity_Plan_Case_Type",
                "February",
                2025,
                filter_values={"Centene_Capacity_Plan_Main_LOB": ["Amisys Medicaid"]}
            )
            ['Claims Processing', 'Enrollment']
        """
        # Generate cache key
        model_name = self.Model.__name__
        filter_key = ""
        if filter_values:
            # Convert filter_values dict to sorted string for cache key
            filter_parts = []
            for col, vals in sorted(filter_values.items()):
                sorted_vals = sorted(vals) if vals else []
                filter_parts.append(f"{col}=[{','.join(sorted_vals)}]")
            filter_key = f"&filters={';'.join(filter_parts)}"

        cache_key = f"distinct:{model_name}:{column_name}:month={month or 'None'}&year={year or 'None'}{filter_key}"

        # Check cache first
        cached_result = _distinct_values_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"[DBManager] Cache hit for get_distinct_values: {cache_key}")
            return cached_result

        # Cache miss - execute query
        logger.debug(f"[DBManager] Cache miss for get_distinct_values: {cache_key}")

        with self.SessionLocal() as session:
            try:
                # Get column object using getattr (database-agnostic)
                column = getattr(self.Model, column_name)

                # Build query using func.distinct() - translates to native DISTINCT on both DBs
                query = session.query(func.distinct(column))

                # Apply month/year filter using existing method
                if month and year:
                    query = self.filter_by_month_and_year(query, month, year)

                # Apply additional column filters (for worktype filtering by Main_LOB)
                if filter_values:
                    for col_name, allowed_values in filter_values.items():
                        if allowed_values:
                            filter_column = getattr(self.Model, col_name)
                            # Use .in_() for SQL IN clause (database-agnostic)
                            query = query.filter(filter_column.in_(allowed_values))

                # Filter out None/empty values (database-agnostic NULL check)
                query = query.filter(column.isnot(None), column != '')

                # Execute query
                results = query.all()

                # Extract values from result tuples
                values = [row[0] for row in results if row[0]]

                # Sort
                sorted_values = sorted(values)

                # Cache the result before returning
                _distinct_values_cache.set(cache_key, sorted_values)
                logger.debug(f"[DBManager] Cached result for: {cache_key} ({len(sorted_values)} values)")

                return sorted_values

            except AttributeError:
                logger.error(f"[DBManager] Column '{column_name}' does not exist on {self.Model.__name__}")
                return []
            except Exception as e:
                logger.error(f"[DBManager] Error getting distinct values for {column_name}: {e}", exc_info=True)
                return []

    def update_records(self, df:pd.DataFrame, month:str, year:int, keys:List[str]=None, updated_by='system'):
        """
        Updates existing forecast records in DB for the given month/year
        using data in df, without inserting new records or touching CreatedBy/CreatedDateTime.
        Only sets UpdatedBy and UpdatedDateTime.
        """
        updates = 0
        session = self.SessionLocal()
        try:
            # For each row in the dataframe:
            for _, row in df.iterrows():
                normalized_month = normalize_month(month)
                # Build filter (add more keys if needed to uniquely identify a row)
                q = session.query(self.Model).filter_by(Month=normalized_month, Year=year)
                # Add more fields if you have a composite key (e.g., ID, LOB, etc.)
                # Add filters for all required columns as keys (example: LOB, State, etc.)
                for key in keys:
                    if key in row:
                        q = q.filter(func.lower(getattr(self.Model, key)) == str(row[key]).lower().strip())
                # Fetch the record
                record = q.first()
                if record:
                    # Update all data fields except CreatedBy/CreatedDateTime
                    for col in df.columns:
                        if col not in ('id', 'CreatedBy', 'CreatedDateTime', 'Month', 'Year'):
                            if hasattr(record, col):
                                setattr(record, col, row[col])
                    # Set audit fields
                    record.UpdatedBy = updated_by
                    updates += 1
                # else: If you want to log that a row was not found, log here
            session.commit()
            logger.info(f"updates done - {updates}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error during forecast record update: {e}")
            raise
        finally:
            session.close()

    def sum_metrics(
        self,
        month: str,
        year: int,
        main_lob: str,
        case_type: str,
    ) -> Dict[str, int]:
        """
        Sum the numeric metric columns for rows matching the filters.

        Rules:
        - Case-sensitive, exact matches; trims both the inputs and the DB-side values.
        - Treat NULLs as 0 via COALESCE(SUM(col), 0).
        - If no rows match, return a dict with the same keys but all values == 0.
        - Performance: single aggregate query, no row materialization.

        Returns:
            Dict[str, int]: {metric_column_name: summed_value}
        """
        Model = self.Model

        # Trim incoming inputs; keep case as-is (case-sensitive comparison)
        month_val = month.strip()
        lob_val = main_lob.strip().lower()
        case_type_val = case_type.strip().lower()

        logger.info("[DBManager] sum_metrics start")
        logger.debug(
            "[DBManager] Filters -> Month='%s', Year=%s, Main LOB='%s', Case Type='%s'",
            month_val, year, lob_val, case_type_val
        )

        # Build aggregate expressions once (fast path)
        agg_exprs = [
            func.coalesce(func.sum(getattr(Model, col)), 0).label(col)
            for col in self.METRIC_COLUMNS
        ]
        # Count the matched rows without GROUP BY (still 1-row aggregate query)
        rowcount_expr = func.count(literal_column("*")).label("_rowcount")

        with self.SessionLocal() as session:
            try:
                # NOTE: func.trim() on columns ensures whitespace-insensitive match;
                # it may bypass an index if one exists on those columns. For max performance,
                # consider normalizing data at write-time or adding generated/functional indexes.
                result_row = (
                    session.query(*agg_exprs, rowcount_expr)
                    .filter(
                        func.trim(Model.Month) == month_val,
                        Model.Year == year,
                        func.lower(func.trim(Model.Centene_Capacity_Plan_Main_LOB)) == lob_val,
                        func.lower(func.trim(Model.Centene_Capacity_Plan_Case_Type)) == case_type_val,
                    )
                    .one()
                )

                rowcount = int(result_row._mapping["_rowcount"])
                if rowcount == 0:
                    logger.warning("[DBManager] sum_metrics: no rows matched filters")
                    return self._zero_metrics_dict()

                # Convert to a plain dict[int]; COALESCE ensures non-NULLs already
                out: Dict[str, int] = {
                    col: int(result_row._mapping[col] or 0) for col in self.METRIC_COLUMNS
                }
                logger.info("[DBManager] sum_metrics success (rows=%d)", rowcount)
                return out

            except Exception as e:
                logger.error("[DBManager] sum_metrics failed: %s", str(e), exc_info=True)
                raise

    def download_db(self, month:str, year:int):
        with self.SessionLocal() as session:
            query = session.query(self.Model)
            if month and year:
                query = self.filter_by_month_and_year(query, month, year)
            records = self._execute_query(query)


            df = pd.DataFrame(records['records'])
            return df

    def get_totals(self):
        with self.SessionLocal() as session:
            query = session.query(self.Model)
            total = query.count()
        return total

    def get_latest_month_year(self):
        """
        Returns the latest (most recent) Month and Year, assuming entries exist.
        """
        with self.SessionLocal() as session:
            try:
                latest = session.query(self.Model.Month, self.Model.Year).order_by(
                    self.Model.Year.desc(),
                    self.Model.Month.desc()
                ).first()

                if not latest:
                    return None

                return {"Month": latest.Month, "Year": latest.Year}

            except Exception as e:
                logger.error(f"[DBManager] Failed to get latest month/year: {str(e)}")
                return None

    def save_allocation_report(
        self,
        df: pd.DataFrame,
        month: str,
        year: int,
        report_type: str,
        created_by: str,
        updated_by: str = None
    ):
        """
        Save allocation report to database using UPSERT logic.
        If a report with the same (Month, Year, ReportType) exists, it will be replaced.

        Args:
            df: DataFrame containing the report data
            month: Month name (e.g., 'January')
            year: Year (e.g., 2025)
            report_type: Type of report ('bucket_summary', 'bucket_after_allocation', 'roster_allotment')
            created_by: User who created/updated the report
            updated_by: User who updated the report (defaults to created_by)
        """
        session = self.SessionLocal()
        Model = AllocationReportsModel

        try:
            normalized_month = normalize_month(month)
            if updated_by is None:
                updated_by = created_by

            # Convert DataFrame to JSON string
            report_json = df.to_json(orient='records', date_format='iso')

            # Check if report already exists
            existing_report = session.query(Model).filter(
                and_(
                    Model.Month == normalized_month,
                    Model.Year == year,
                    Model.ReportType == report_type
                )
            ).first()

            if existing_report:
                # Update existing report
                existing_report.ReportData = report_json
                existing_report.UpdatedBy = updated_by
                existing_report.UpdatedDateTime = datetime.now()
                logger.info(f"[DBManager] Updated allocation report: {report_type} for {normalized_month} {year}")
            else:
                # Insert new report
                new_report = Model(
                    Month=normalized_month,
                    Year=year,
                    ReportType=report_type,
                    ReportData=report_json,
                    CreatedBy=created_by,
                    UpdatedBy=updated_by
                )
                session.add(new_report)
                logger.info(f"[DBManager] Inserted new allocation report: {report_type} for {normalized_month} {year}")

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"[DBManager] Error saving allocation report: {e}")
            raise
        finally:
            session.close()

    def get_allocation_report(
        self,
        month: str,
        year: int,
        report_type: str
    ) -> Optional[str]:
        """
        Retrieve allocation report as JSON string.

        Args:
            month: Month name (e.g., 'January')
            year: Year (e.g., 2025)
            report_type: Type of report ('bucket_summary', 'bucket_after_allocation', 'roster_allotment')

        Returns:
            JSON string of the report data, or None if not found
        """
        session = self.SessionLocal()
        Model = AllocationReportsModel

        try:
            normalized_month = normalize_month(month)

            report = session.query(Model).filter(
                and_(
                    Model.Month == normalized_month,
                    Model.Year == year,
                    Model.ReportType == report_type
                )
            ).first()

            if report:
                logger.info(f"[DBManager] Retrieved allocation report: {report_type} for {normalized_month} {year}")
                return report.ReportData
            else:
                logger.info(f"[DBManager] No allocation report found: {report_type} for {normalized_month} {year}")
                return None

        except Exception as e:
            logger.error(f"[DBManager] Error retrieving allocation report: {e}")
            raise
        finally:
            session.close()

    def get_allocation_report_as_dataframes(
        self,
        month: str,
        year: int,
        report_type: str
    ) -> Optional[pd.DataFrame]:
        """
        Retrieve allocation report and convert to DataFrame.

        Args:
            month: Month name (e.g., 'January')
            year: Year (e.g., 2025)
            report_type: Type of report ('bucket_summary', 'bucket_after_allocation', 'roster_allotment')

        Returns:
            DataFrame containing the report data, or None if not found
        """
        try:
            report_json = self.get_allocation_report(month, year, report_type)

            if report_json:
                # Convert JSON string back to DataFrame
                import json
                df = pd.DataFrame(json.loads(report_json))
                logger.info(f"[DBManager] Converted allocation report to DataFrame: {report_type} ({len(df)} rows)")
                return df
            else:
                return None

        except Exception as e:
            logger.error(f"[DBManager] Error converting allocation report to DataFrame: {e}")
            raise

    def get_forecast_months_list(self, month:str, year:int, filename:str=None) -> List[str]:
        if not (month and year):
            logger.error(f"month or year value is missing")
            return []
        try:
            with self.SessionLocal() as session:

                if filename:
                    forecast_months_record = session.query(ForecastMonthsModel).filter(
                        ForecastMonthsModel.UploadedFile == filename
                    ).order_by(
                        ForecastMonthsModel.CreatedDateTime.desc()
                    ).first()
                else:
                    query = session.query(ForecastModel)
                    query=self.filter_by_month_and_year(query, month, year)
                    query = query.order_by(ForecastModel.UpdatedDateTime.desc()).limit(1)
                    forecast_record = query.first()


                    if not forecast_record:
                        logger.error(f"Forecast data not availbale for the month: {month} year: {year}")
                        return []

                    forecast_months_record = session.query(ForecastMonthsModel).filter(
                        ForecastMonthsModel.UploadedFile == forecast_record.UploadedFile
                    ).order_by(
                        ForecastMonthsModel.CreatedDateTime.desc()
                    ).first()

        except Exception as e:
            logger.error(f"Error occured: {e}")
            return []
        return [
            getattr(forecast_months_record, f"Month{i}", None) for i in range(1,7)
        ]

    def insert_upload_data_time_details_if_not_exists(self, month: str, year: int):
        """
        Insert (month, year) into UploadDataTimeDetails if not already present.
        """
        session = self.SessionLocal()
        try:
            normalized_month = normalize_month(month)
            exists = session.query(UploadDataTimeDetails).filter(
                UploadDataTimeDetails.Month == normalized_month,
                UploadDataTimeDetails.Year == year
            ).first()
            if not exists:
                new_record = UploadDataTimeDetails(Month=normalized_month, Year=year)
                session.add(new_record)
                session.commit()
                logger.info(f"Inserted UploadDataTimeDetails: {normalized_month}, {year}")
                return True
            else:
                logger.info(f"UploadDataTimeDetails already exists: {normalized_month}, {year}")
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"Error inserting UploadDataTimeDetails: {e}")
            raise
        finally:
            session.close()





if __name__=="__main__":
    columns = []
    for key, value in typing.get_type_hints(ForecastModel).items():
        if value==str or Optional[str]:
            columns.append(key)

    print(columns)