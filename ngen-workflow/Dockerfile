FROM --platform=linux/amd64 rocker/geospatial:4

RUN Rscript -e "install.packages('sf', type = 'source')"
RUN Rscript -e "install.packages('remotes')"
RUN Rscript -e "remotes::install_github('lynker-spatial/hfutils@f74e9a41beaddf539c9420fc0f01ed1dc18820a2')"
RUN Rscript -e "remotes::install_github('lynker-spatial/hfrefactor')"
RUN Rscript -e "remotes::install_github('CUAHSI/hfaggregate')"
RUN Rscript -e "whitebox::install_whitebox()"
RUN Rscript -e "install.packages('nanoarrow')"
RUN Rscript -e "remotes::install_github('NOAA-OWP/hydrofabric')"
RUN Rscript -e "install.packages('aws.s3')"
RUN Rscript -e "install.packages('arrow')"
RUN Rscript -e "install.packages('glue')"

RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

# Install Miniconda
ENV CONDA_DIR /opt/conda
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda.sh && \
    /bin/bash ~/miniconda.sh -b -p /opt/conda && \
    rm ~/miniconda.sh

# Put Conda in PATH
ENV PATH=$CONDA_DIR/bin:$PATH

RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
RUN conda install -c conda-forge -y libgdal-arrow-parquet

RUN echo 'DYLD_LIBRARY_PATH=/usr/local/lib:/usr/local/Cellar/libspatialite/5.1.0_3/lib:$./' >> ~/.Renviron
RUN echo 'GDAL_DRIVER_PATH=/usr/local/lib' >> ~/.Renviron

RUN mkdir /ngen-workflow
WORKDIR /ngen-workflow

ENTRYPOINT [ "sh" ]