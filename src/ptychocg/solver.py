"""Module for 2D ptychography."""

import warnings

import cupy as cp
import numpy as np
import dxchange
import sys
import signal
from ptychocg.ptychofft import ptychofft
warnings.filterwarnings("ignore")


class Solver(object):
    def __init__(self, prbmaxint, nscan, nprb, ndetx, ndety, ntheta, nz, n, ptheta):

        self.nscan = nscan
        self.nprb = nprb
        self.ntheta = ntheta
        self.nz = nz
        self.n = n
        self.nscan = nscan
        self.ndetx = ndetx
        self.ndety = ndety
        self.nprb = nprb
        self.ptheta = ptheta
        self.prbmaxint = prbmaxint

        # create class for the ptycho transform
        self.cl_ptycho = ptychofft(
            self.ptheta, self.nz, self.n, self.nscan, self.ndetx, self.ndety, self.nprb)
    
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTSTP, self.signal_handler)

    def signal_handler(self, sig, frame):  # Free gpu memory after SIGINT, SIGSTSTP (destructor)
        self = []
        sys.exit(0)

    # Ptychography transform (FQ)
    def fwd_ptycho(self, psi, scan, prb):
        res = cp.zeros([self.ptheta, self.nscan, self.ndety,
                        self.ndetx], dtype='complex64', order='C')
        self.cl_ptycho.fwd(res.data.ptr, psi.data.ptr,
                           scan.data.ptr, prb.data.ptr)
        return res

    # Batch of Ptychography transform (FQ)
    def fwd_ptycho_batch(self, psi, scan, prb):
        data = np.zeros([self.ntheta, self.nscan, self.ndety,
                         self.ndetx], dtype='float32', order='C')
        for k in range(0, self.ntheta//self.ptheta):  # angle partitions in ptychography
            ids = np.arange(k*self.ptheta, (k+1)*self.ptheta)
            data0 = cp.abs(self.fwd_ptycho(
                psi[ids], scan[:, ids], prb[ids]))**2
            data[ids] = data0.get()
        return data

    # Adjoint ptychography transform (Q*F*), probe is fixed
    def adj_ptycho(self, data, scan, prb):
        res = cp.zeros([self.ptheta, self.nz, self.n],
                       dtype='complex64', order='C')
        self.cl_ptycho.adj(res.data.ptr, data.data.ptr,
                           scan.data.ptr, prb.data.ptr)
        return res

    # Adjoint ptychography probe transform (O*F*), object is fixed
    def adj_ptychoq(self, data, scan, psi):
        res = cp.zeros([self.ptheta, self.nprb, self.nprb],
                       dtype='complex64', order='C')
        self.cl_ptycho.adjq(res.data.ptr, data.data.ptr,
                            scan.data.ptr, psi.data.ptr)
        return res

    # Line search for the step sizes gamma
    def line_search(self, minf, gamma, u, fu, d, fd):
        while(minf(u, fu)-minf(u+gamma*d, fu+gamma*fd) < 0 and gamma > 1e-32):
            gamma *= 0.5
        if(gamma <= 1e-32):  # direction not found
            gamma = 0
        return gamma

    # Conjugate gradients for ptychography
    def cg_ptycho(self, data, psi, scan, prb, piter, model):
        # minimization functional
        def minf(psi, fpsi):
            if model == 'gaussian':
                f = cp.linalg.norm(cp.abs(fpsi)-cp.sqrt(data))**2
            elif model == 'poisson':
                f = cp.sum(cp.abs(fpsi)**2-2*data * cp.log(cp.abs(fpsi)+1e-32))
            return f

        for i in range(piter):
            # initial gradient steps
            gammapsi = 1/(self.prbmaxint**2)
            gammaprb = 1

            # 1) CG update psi with fixed prb
            fpsi = self.fwd_ptycho(psi, scan, prb)
            if model == 'gaussian':
                gradpsi = self.adj_ptycho(
                    fpsi-cp.sqrt(data)*cp.exp(1j*cp.angle(fpsi)), scan, prb)
            elif model == 'poisson':
                gradpsi = self.adj_ptycho(
                    fpsi-data*fpsi/(cp.abs(fpsi)**2+1e-32), scan, prb)
            # Dai-Yuan direction
            if i == 0:
                dpsi = -gradpsi
            else:
                dpsi = -gradpsi+cp.linalg.norm(gradpsi)**2 / \
                    ((cp.sum(cp.conj(dpsi)*(gradpsi-gradpsi0))))*dpsi
            gradpsi0 = gradpsi
            # line search
            fdpsi = self.fwd_ptycho(dpsi, scan, prb)
            gammapsi = self.line_search(minf, gammapsi, psi, fpsi, dpsi, fdpsi)
            # update psi
            psi = psi + gammapsi*dpsi

            # 2) CG update prb with fixed psi
            fpsi = self.fwd_ptycho(psi, scan, prb)
            if model == 'gaussian':
                gradprb = self.adj_ptychoq(
                    fpsi-cp.sqrt(data)*cp.exp(1j*cp.angle(fpsi)), scan, psi)/self.nscan
            elif model == 'poisson':
                gradprb = self.adj_ptychoq(
                    fpsi-data*fpsi/(cp.abs(fpsi)**2+1e-32), scan, psi)/self.nscan
            # Dai-Yuan direction
            if i == 0:
                dprb = -gradprb
            else:
                dprb = -gradprb+cp.linalg.norm(gradprb)**2 / \
                    ((cp.sum(cp.conj(dprb)*(gradprb-gradprb0))))*dprb
            gradprb0 = gradprb
            # line search
            fdprb = self.fwd_ptycho(psi, scan, dprb)
            gammaprb = self.line_search(
                minf, gammaprb, psi, fpsi, psi, fdprb)
            # update prb
            prb = prb + gammaprb*dprb

            print(i, gammapsi, gammaprb, minf(psi, fpsi))

        if(cp.amax(cp.abs(cp.angle(psi))) > 3.14):
            print('possible phase wrap, max computed angle',
                  cp.amax(cp.abs(cp.angle(psi))))

        return psi, prb

    # Solve ptycho by angles partitions
    def cg_ptycho_batch(self, data, initpsi, scan, initprb, piter, model):
        psi = initpsi.copy()
        prb = initprb.copy()

        for k in range(0, self.ntheta//self.ptheta):
            ids = np.arange(k*self.ptheta, (k+1)*self.ptheta)
            datap = cp.array(data[ids])
            psi[ids], prb[ids] = self.cg_ptycho(
                datap, psi[ids], scan[:, ids], prb[ids], piter, model)
        return psi, prb
