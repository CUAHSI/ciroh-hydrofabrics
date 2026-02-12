
### Configure Dependencies

Install gdal and sqlite

```
brew install gdal libspatialite sqlite
```

Make sure gdal is compiled with spatialite support

```
gdalinfo --formats | grep -i spatial
```

Install `sf` with spatialite support by compiling from source

```
install.packages("sf", type = "source")
```

### Install HFRefactor

```
install.packages("remotes")
```

```
remotes::install_github("lynker-spatial/hfutils@f74e9a41beaddf539c9420fc0f01ed1dc18820a2") 
```

```
remotes::install_github("lynker-spatial/hfrefactor")
```

```
whitebox::install_whitebox()
```

```
install.packages("nanoarrow")
```

### Setup R Environment Paths

```
echo 'DYLD_LIBRARY_PATH=/usr/local/lib:/usr/local/Cellar/libspatialite/5.1.0_3/lib:$DYLD_LIBRARY_PATH' >> ~/.Renviron
```

```
echo 'GDAL_DRIVER_PATH=/usr/local/lib' >> ~/.Renviron
```



