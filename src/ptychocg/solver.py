"""Module for 2D ptychography."""

import warnings

import cupy as cp
import numpy as np
import dxchange
from ptychocg.ptychofft import ptychofft
import time

warnings.filterwarnings("ignore")


class Solver(object):
    def __init__(self, prbmaxint, nscan, nprb, det, ntheta, nz, n):

        self.ntheta = ntheta
        self.nz = nz
        self.n = n
        self.nscan = nscan
        self.ndety = det[0]
        self.ndetx = det[1]
        self.nprb = nprb

        # create class for the ptycho transform
        self.cl_ptycho = ptychofft(
            self.ntheta, self.nz, self.n, self.nscan, self.ndetx, self.ndety, self.nprb)
        # normalization coefficients
        self.coefptycho = 1 / prbmaxint
        self.coefdata = 1 / (self.ndetx*self.ndety * prbmaxint**2)  # check

    def mlog(self, psi):
        res = psi.copy()
        res[cp.abs(psi) < 1e-32] = 1e-32
        res = cp.log(res)
        return res

    # Ptychography transform (FQ)
    def fwd_ptycho(self, psi, scan, prb):
        res = cp.zeros([self.ntheta, self.nscan, self.ndety,
                        self.ndetx], dtype='complex64', order='C')
        self.cl_ptycho.fwd(res.data.ptr, psi.data.ptr,
                           scan.data.ptr, prb.data.ptr)
        res *= self.coefptycho  # normalization
        return res

    # Batch of Ptychography transform (FQ)
    def fwd_ptycho_batch(self, psi, scan, prb):
        data = np.zeros([self.ntheta, self.nscan, self.ndety,
                         self.ndetx], dtype='float32')
        for k in range(0, 1):  # angle partitions in ptychography
            ids = np.arange(k*self.ntheta, (k+1)*self.ntheta)
            data0 = cp.abs(self.fwd_ptycho(
                psi[ids], scan[:, ids], prb[ids]))**2/self.coefdata
            data[ids] = data0.get()
        return data

    # Adjoint ptychography transform (Q*F*)
    def adj_ptycho(self, data, scan, prb):
        res = cp.zeros([self.ntheta, self.nz, self.n],
                       dtype='complex64', order='C')
        self.cl_ptycho.adj(res.data.ptr, data.data.ptr,
                           scan.data.ptr, prb.data.ptr)
        res *= self.coefptycho  # normalization
        return res

    # Line search for the step sizes gamma
    def line_search(self, minf, gamma, u, fu, d, fd):
        while(minf(u, fu)-minf(u+gamma*d, fu+gamma*fd) < 0 and gamma > 1e-32):
            gamma *= 0.5
        if(gamma <= 1e-20):  # direction not found
            gamma = 0
        return gamma

    # Conjugate gradients for ptychography
    def cg_ptycho(self, data, init, scan, prb, piter, model):
        # minimization functional
        def minf(psi, fpsi):
            if model == 'gaussian':
                f = cp.linalg.norm(cp.abs(fpsi)-cp.sqrt(data))**2
            elif model == 'poisson':
                f = cp.sum(cp.abs(fpsi)**2-2*data * self.mlog(cp.abs(fpsi)))
            #f += rho*cp.linalg.norm(h-psi+lamd/rho)**2
            return f

        psi = init.copy()
        gamma = 2  # init gamma as a large value

        for i in range(piter):
            fpsi = self.fwd_ptycho(psi, scan, prb)
            if model == 'gaussian':
                grad = self.adj_ptycho(
                    fpsi-cp.sqrt(data)*cp.exp(1j*cp.angle(fpsi)), scan, prb)
            elif model == 'poisson':
                grad = self.adj_ptycho(
                    fpsi-data*fpsi/(cp.abs(fpsi)**2+1e-32), scan, prb)
            # Dai-Yuan direction
            if i == 0:
                d = -grad
            else:
                d = -grad+cp.linalg.norm(grad)**2 / \
                    ((cp.sum(cp.conj(d)*(grad-grad0))))*d
            grad0 = grad
            # line search
            fd = self.fwd_ptycho(d, scan, prb)
            gamma = self.line_search(minf, gamma, psi, fpsi, d, fd)
            psi = psi + gamma*d
            if(np.mod(i, 16) == 0):
                print(i, minf(psi, fpsi))

        if(cp.amax(cp.abs(cp.angle(psi))) > 3.14):
            print('possible phase wrap, max computed angle',
                  cp.amax(cp.abs(cp.angle(psi))))

        return psi

    # Solve ptycho by angles partitions
    def cg_ptycho_batch(self, data, init, scan, prb, piter, model):
        psi = init.copy()
        for k in range(0, 1):
            ids = np.arange(k*self.ntheta, (k+1)*self.ntheta)
            datap = cp.array(data[ids])*self.coefdata  # normalized data
            psi[ids] = self.cg_ptycho(
                datap, psi[ids], scan[:, ids], prb[ids], piter, model)
        return psi