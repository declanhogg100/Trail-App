FROM python:3.12-slim

# api's pyproject.toml declares recommender/time_estimator as *editable*
# path dependencies (../recommender, ../time_estimator) -- uv installs those
# as links back to these directories rather than copying their code in, so
# the sibling layout has to be preserved under WORKDIR exactly like this,
# not flattened.
WORKDIR /app
COPY api ./api
COPY recommender ./recommender
COPY time_estimator ./time_estimator

# recommender's data/dem (29GB of elevation tiles) and the other large
# parquet files are deliberately NOT copied into the image here -- they're
# bind-mounted from the host's persistent volume at container start (see
# docker-compose.yml). Baking 29GB of terrain data into the image would make
# every rebuild/redeploy absurdly slow for data that doesn't change when the
# code does.

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# rasterio/pyogrio/shapely ship their own GDAL/GEOS/PROJ in their manylinux
# wheels, so no system packages (libgdal-dev etc.) should be needed -- if
# the build below fails on a missing shared library, that's the first place
# to look.
RUN cd api && uv sync --frozen --no-dev

EXPOSE 8000
WORKDIR /app/api
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
