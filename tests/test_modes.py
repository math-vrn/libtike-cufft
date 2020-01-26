import sys

import dxchange
import cupy as cp
import numpy as np
from scipy import ndimage

import libtike.cufft as pt

if __name__ == "__main__":

    if (len(sys.argv) < 2):
        igpu = 0
    else:
        igpu = np.int(sys.argv[1])

    # sizes
    n = 600  # horizontal size
    nz = 276  # vertical size
    ntheta = 1  # number of projections
    nscan = 1100  # number of scan positions [max 5706 for the data example]
    nprb = 128  # probe size
    ndet = 128  # detector x size
    recover_prb = True  # True: recover probe, False: use the initial one
    # Reconstrucion parameters
    model = 'gaussian'  # minimization funcitonal (poisson,gaussian)
    piter = 64 # ptychography iterations
    ptheta = 1  # number of angular partitions for simultaneous processing in ptychography    
    nmodes = 1 # number of probe modes for decomposition in reconstruction (for the test compare results for nmodes=1,2)
    nmodes_gen = 2 # number of probe modes for decomposition in data generation (nmodes_gen>nmodes)
    # read probe
    prb0 = np.zeros([ntheta,nmodes_gen, nprb, nprb], dtype='complex64')
    prbamp = dxchange.read_tiff('model/probes_amp.tiff')[0:nmodes_gen].astype('float32')
    prbang = dxchange.read_tiff('model/probes_ang.tiff')[0:nmodes_gen].astype('float32')
    prb0[0] = prbamp*np.exp(1j*prbang)

    # read scan positions
    scan = np.ones([ntheta, nscan, 2], dtype='float32')
    temp = np.moveaxis(np.load('model/coords.npy'), 0, 1)[:nscan*5:5]
    scan[0, :, 0] = temp[:, 1]
    scan[0, :, 1] = temp[:, 0]

    # read object
    psi0 = np.ones([ntheta, nz, n], dtype='complex64')
    psiamp = dxchange.read_tiff('model/initpsiamp.tiff').astype('float32')
    psiang = dxchange.read_tiff('model/initpsiang.tiff').astype('float32')
    psi0[0] = psiamp*np.exp(1j*psiang)

    # Class gpu solver
    with pt.CGPtychoSolver(nscan, nprb, ndet, ptheta, nz, n) as slv:
        # Compute intensity data on the detector |FQ|**2
        data = np.zeros([ntheta,nscan,ndet,ndet],dtype='float32')
        for k in range(nmodes_gen):
            data += np.abs(slv.fwd_ptycho_batch(psi0, scan, prb0[:,k]))**2
        dxchange.write_tiff(data, 'data', overwrite=True)
        
        # Initial guess
        psi = np.ones([ntheta, nz, n], dtype='complex64')
        if (recover_prb):
            # Choose an adequate probe approximation
            prb = prb0[:,:nmodes].copy()
        else:
            prb = prb0.copy()
        result = slv.run_batch(
             data, psi, scan, prb, piter=piter, model=model, recover_prb=recover_prb)
        psi, prb = result['psi'], result['probe']

    # Save result
    name = str(model)+str(nmodes)+'modes'+str(piter)+'iters'
    dxchange.write_tiff(np.angle(psi),
                        'rec/psiang'+name, overwrite=True)
    dxchange.write_tiff(np.abs(psi),  'rec/prbamp'+name, overwrite=True)

    # recovered
    dxchange.write_tiff(np.angle(prb),
                        'rec/prbangle'+name, overwrite=True)
    dxchange.write_tiff(np.abs(prb),  'rec/prbamp'+name, overwrite=True)
    # init
    dxchange.write_tiff(np.angle(prb0),
                        'rec/prb0angle'+name, overwrite=True)
    dxchange.write_tiff(np.abs(prb0),
                        'rec/prb0amp'+name, overwrite=True)

    # plot result
    import matplotlib.pyplot as plt
    plt.figure(figsize=(11, 7))
    plt.subplot(2, 2, 1)
    plt.title('scan positions')
    plt.plot(scan[0, :, 0], scan[0, :, 1],
             '.', markersize=1.5, color='blue')
    plt.xlim([0, n])
    plt.ylim([0, nz])
    plt.gca().invert_yaxis()
    plt.subplot(2, 4, 1)
    plt.title('correct prb phase')
    plt.imshow(np.angle(prb0[0,0]), cmap='gray')
    plt.colorbar()
    plt.subplot(2, 4, 2)
    plt.title('correct prb amplitude')
    plt.imshow(np.abs(prb0[0,0]), cmap='gray')
    plt.colorbar()
    plt.subplot(2, 4, 3)
    plt.title('retrieved probe phase')
    plt.imshow(np.angle(prb[0,0]), cmap='gray')
    plt.colorbar()
    plt.subplot(2, 4, 4)
    plt.title('retrieved probe amplitude')
    plt.imshow(np.abs(prb[0,0]), cmap='gray')
    plt.colorbar()
    plt.subplot(2, 2, 3)
    plt.title('object phase')
    plt.imshow(np.angle(psi[0]), cmap='gray')
    plt.colorbar()
    plt.subplot(2, 2, 4)
    plt.title('object amplitude')
    plt.imshow(np.abs(psi[0]), cmap='gray')
    plt.colorbar()
    plt.savefig('result.png', dpi=600)
    print("See result.png and tiff files in rec/ folder")
