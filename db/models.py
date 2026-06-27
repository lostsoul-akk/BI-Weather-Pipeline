"""
db/models.py
SQLAlchemy ORM models — mirror of db/schema.sql.
"""

from sqlalchemy import (
    Column, Integer, SmallInteger, Float, String, Text,
    DateTime, Date, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    city_id   = Column(Integer, primary_key=True, autoincrement=True)
    city_name = Column(String(100), nullable=False)
    country   = Column(String(2),   nullable=False)
    latitude  = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    weather_readings    = relationship("WeatherReading",    back_populates="city")
    air_quality_readings = relationship("AirQualityReading", back_populates="city")
    daily_summaries     = relationship("DailySummary",       back_populates="city")

    __table_args__ = (UniqueConstraint("city_name", "country"),)

    def __repr__(self):
        return f"<City {self.city_name}, {self.country}>"


class WeatherReading(Base):
    __tablename__ = "weather_readings"

    reading_id          = Column(Integer, primary_key=True, autoincrement=True)
    city_id             = Column(Integer, ForeignKey("cities.city_id", ondelete="CASCADE"), nullable=False)
    recorded_at         = Column(DateTime(timezone=True), nullable=False)
    temperature_c       = Column(Float)
    feels_like_c        = Column(Float)
    temp_min_c          = Column(Float)
    temp_max_c          = Column(Float)
    humidity_pct        = Column(Float)
    pressure_hpa        = Column(Float)
    wind_speed_ms       = Column(Float)
    wind_deg            = Column(SmallInteger)
    cloudiness_pct      = Column(SmallInteger)
    visibility_m        = Column(Integer)
    weather_main        = Column(String(50))
    weather_description = Column(String(200))
    validation_flag     = Column(Text, default="")

    city = relationship("City", back_populates="weather_readings")

    __table_args__ = (
        UniqueConstraint("city_id", "recorded_at"),
        Index("idx_weather_city_time", "city_id", "recorded_at"),
    )


class AirQualityReading(Base):
    __tablename__ = "air_quality_readings"

    reading_id      = Column(Integer, primary_key=True, autoincrement=True)
    city_id         = Column(Integer, ForeignKey("cities.city_id", ondelete="CASCADE"), nullable=False)
    recorded_at     = Column(DateTime(timezone=True), nullable=False)
    aqi             = Column(SmallInteger)
    aqi_category    = Column(String(20))
    co              = Column(Float)
    no              = Column(Float)
    no2             = Column(Float)
    o3              = Column(Float)
    so2             = Column(Float)
    pm2_5           = Column(Float)
    pm10            = Column(Float)
    nh3             = Column(Float)
    validation_flag = Column(Text, default="")

    city = relationship("City", back_populates="air_quality_readings")

    __table_args__ = (
        UniqueConstraint("city_id", "recorded_at"),
        Index("idx_aqi_city_time", "city_id", "recorded_at"),
    )


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    summary_id       = Column(Integer, primary_key=True, autoincrement=True)
    city_id          = Column(Integer, ForeignKey("cities.city_id", ondelete="CASCADE"), nullable=False)
    summary_date     = Column(Date, nullable=False)
    avg_temp_c       = Column(Float)
    min_temp_c       = Column(Float)
    max_temp_c       = Column(Float)
    avg_humidity     = Column(Float)
    avg_wind_ms      = Column(Float)
    avg_aqi          = Column(Float)
    max_aqi          = Column(SmallInteger)
    dominant_weather = Column(String(50))

    city = relationship("City", back_populates="daily_summaries")

    __table_args__ = (
        UniqueConstraint("city_id", "summary_date"),
        Index("idx_summary_city_date", "city_id", "summary_date"),
    )
