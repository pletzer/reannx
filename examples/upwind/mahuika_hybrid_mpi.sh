# Hybrid MPI on mahuika: Slurm (srun --mpi=pmi2) launches the ranks; Intel MPI inside
# the container wires up via the host PMI2 and talks over InfiniBand using the host UCX.
# Adapted from fidibench_apptainer/upwindMpiCxx_apptainer.sl. Appends to $REANNX_BINDS.
binds=""
binds+=",/usr/lib64/libpmi2.so.0:/.singularity.d/libs/libpmi2.so"
for lib in libibverbs.so.1 librdmacm.so.1 libmlx5.so.1 \
           libucp.so.0 libuct.so.0 libucs.so.0 libucm.so.0; do
    binds+=",$(readlink -f /usr/lib64/$lib):/usr/lib64/$lib"
done
for drv in /usr/lib64/libibverbs/*.so; do
    binds+=",$(readlink -f $drv):$drv"
done
binds+=",/etc/libibverbs.d:/etc/libibverbs.d,/usr/lib64/ucx:/usr/lib64/ucx"
REANNX_BINDS="$REANNX_BINDS$binds"
ibdev=$(for d in /sys/class/infiniband/*; do
            [ "$(cat $d/ports/1/link_layer)" = InfiniBand ] && basename $d && break
        done)
export UCX_NET_DEVICES=${UCX_NET_DEVICES:-$ibdev:1}
export UCX_POSIX_USE_PROC_LINK=n
export I_MPI_PMI_LIBRARY=/.singularity.d/libs/libpmi2.so
export I_MPI_FABRICS=shm:ofi
export FI_PROVIDER=${FI_PROVIDER:-mlx}
export I_MPI_DEBUG=5
