#include <cufft.h>

#ifndef _PTYCHOFFT
#define _PTYCHOFFT

class ptychofft
{
  bool is_free = false;

	float2 *f;		// object
	float2 *g;		// data
	float2 *prb;	// probe function
	float2 *scan;   // x,y scan positions
  // Negative scan positions are skipped in kernel executions.

	cufftHandle plan2d;		 // 2D FFT plan
  float2 *fft_out;       // Buffer to store FFT output

	dim3 BS3d; // 3d thread block on GPU

	// 3d thread grids on GPU for different kernels
	dim3 GS3d0;
	dim3 GS3d1;
	dim3 GS3d2;

public:
  size_t ptheta; // number of projections
  size_t nz;	 // object vertical size
  size_t n;	  // object horizontal size
  size_t nscan;  // number of scan positions for 1 projection
  size_t ndet;  // detector size in 1 dimension
  size_t nprb;   // probe size in 1 dimension

	// constructor, memory allocation
	ptychofft(size_t ptheta, size_t nz, size_t n,
			  size_t nscan, size_t ndet, size_t nprb);
	// destructor, memory deallocation
	~ptychofft();
	// forward ptychography operator FQ
	void fwd(size_t g_, size_t f_, size_t scan_, size_t prb_);
	// adjoint ptychography operator with respect to object (fgl==0) f = Q*F*g, or probe (flg==1) prb = Q*F*g
	void adj(size_t f_, size_t g_, size_t scan_, size_t prb_, int flg);
  void free();
};

#endif
