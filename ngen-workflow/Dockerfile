FROM --platform=linux/amd64 rocker/geospatial:4

RUN Rscript -e "install.packages('sf', type = 'source')"
RUN Rscript -e "install.packages('remotes')"
RUN Rscript -e "remotes::install_github('lynker-spatial/hfutils@f74e9a41beaddf539c9420fc0f01ed1dc18820a2')"
RUN Rscript -e "remotes::install_github('lynker-spatial/hfrefactor')"
RUN Rscript -e "whitebox::install_whitebox()"
RUN Rscript -e "install.packages('nanoarrow')"

RUN echo 'DYLD_LIBRARY_PATH=/usr/local/lib:/usr/local/Cellar/libspatialite/5.1.0_3/lib:$./' >> ~/.Renviron
RUN echo 'GDAL_DRIVER_PATH=/usr/local/lib' >> ~/.Renviron

RUN mkdir /hfrefactor
WORKDIR /hfrefactor

ENTRYPOINT [ "sh" ]