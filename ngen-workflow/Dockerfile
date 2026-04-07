FROM rocker/geospatial:4


RUN apt-get update \
 && apt-get install -y \
    wget \
    libglpk40 \
    libglpk-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Miniconda
ENV CONDA_DIR /opt/conda
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O ~/miniconda.sh && \
    /bin/bash ~/miniconda.sh -b -p /opt/conda && \
    rm ~/miniconda.sh

# Put Conda in PATH
ENV PATH=$CONDA_DIR/bin:$PATH

RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
RUN conda install -c conda-forge -y libgdal-arrow-parquet

RUN echo 'DYLD_LIBRARY_PATH=/usr/local/lib:/usr/local/Cellar/libspatialite/5.1.0_3/lib:$./' >> ~/.Renviron
RUN echo 'GDAL_DRIVER_PATH=/usr/local/lib' >> ~/.Renviron

ENV R_FAIL="options(error=function() quit(status=1));"
RUN Rscript -e "$R_FAIL install.packages('remotes'); library(remotes)"
RUN Rscript -e "$R_FAIL install.packages('sf', type = 'source'); library(sf)"
RUN Rscript -e "$R_FAIL remotes::install_github('lynker-spatial/hfutils@f74e9a41beaddf539c9420fc0f01ed1dc18820a2'); library(hfutils)"
RUN Rscript -e "$R_FAIL remotes::install_github('lynker-spatial/hfrefactor'); library(hfrefactor)"
RUN Rscript -e "$R_FAIL remotes::install_github('CUAHSI/hfaggregate'); library(hfaggregate)"
RUN Rscript -e "$R_FAIL whitebox::install_whitebox(); library(whitebox)"
RUN Rscript -e "$R_FAIL install.packages('nanoarrow'); library(nanoarrow)"
RUN Rscript -e "$R_FAIL remotes::install_github('NOAA-OWP/hydrofabric')"
RUN Rscript -e "$R_FAIL install.packages('aws.s3'); library(aws.s3)"
RUN Rscript -e "$R_FAIL install.packages('arrow'); library(arrow)"
RUN Rscript -e "$R_FAIL install.packages('glue'); library(glue)"


RUN mkdir /ngen-workflow
WORKDIR /ngen-workflow

ENTRYPOINT [ "sh" ]
