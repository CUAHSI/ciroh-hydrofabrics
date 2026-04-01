for i in $(seq -w 1 18); do
    dvc import-url remote://superconus/divides/vpuid_${i}.parquet ngen-workflow/data/superconus/divides/vpuid_${i}.parquet --no-download
    dvc import-url remote://superconus/flowpaths/vpuid_${i}.parquet ngen-workflow/data/superconus/flowpaths/vpuid_${i}.parquet --no-download
    dvc import-url remote://superconus/hydrolocations/vpuid_${i}.parquet ngen-workflow/data/superconus/hydrolocations/vpuid_${i}.parquet --no-download
    dvc import-url remote://superconus/network/vpuid_${i}.parquet ngen-workflow/data/superconus/network/vpuid_${i}.parquet --no-download
done
