"""This file implements the NRTidalv2 corrections, see http://arxiv.org/abs/1905.06011"""

# FIXME make sure that jax differentiable is OK

import jax
import jax.numpy as jnp

from ..constants import EulerGamma, gt, m_per_Mpc, C, PI, MSUN
from ..typing import Array
from ripple import Mc_eta_to_ms, ms_to_Mc_eta
import sys


## Unused for now?
# from .IMRPhenomD_QNMdata import fM_CUT
# from .IMRPhenomD_utils import (
#     get_coeffs,
#     get_delta0,
#     get_delta1,
#     get_delta2,
#     get_delta3,
#     get_delta4,
#     get_transition_frequencies,
# )


### TODO remove these, they are not exact
# # Eq. (20)
# C_1 = 3115./1248.
# C_THREE_HALVES = - PI
# C_2 = 28024205./3302208.
# C_FIVE_HALVES = - 4283. * PI / 1092.
#
# # Eq. (21)
#
# N_FIVE_HALVES = 90.550822
# N_3 = -60.253578
# D_1 = -15.111208
# D_2 = 8.0641096

# N_1 = C_1 + D_1
# N_THREE_HALVES = (C_1 * C_THREE_HALVES - C_FIVE_HALVES - C_THREE_HALVES * D_1 + N_FIVE_HALVES) / C_1
# N_2 = C_2 + C_1 * D_1 + D_2
# D_THREE_HALVES = - (C_FIVE_HALVES + C_THREE_HALVES * D_1 - N_FIVE_HALVES) / C_1

# D: just below Eq. (24)
NRTidalv2_coeffs = jnp.array([
    2.4375, # c_Newt
    -12.615214237993088, # n_1
    19.0537346970349, # n_3over2
    -21.166863146081035, # n_2
    90.55082156324926, # n_5over2
    -60.25357801943598, # n_3
    -15.111207827736678, # d_1
    22.195327350624694, # d_3over2
    8.064109635305156, # d_2
])


D = 13477.8

def get_kappa(theta):
    # Sum the two terms to get total kappa
    m1, m2, chi1, chi2, lambda1, lambda2 = theta

    # Convert mass variables
    m1_s = m1 * gt
    m2_s = m2 * gt
    M_s = m1_s + m2_s
    eta = m1_s * m2_s / (M_s**2.0)

    # Compute X
    X1 = m1_s / M_s
    X2 = m2_s / M_s

    term1 = (1.0 + 12.0 * m2 / m1) * X1 ** 5.0 * lambda1
    term2 = (1.0 + 12.0 * m1 / m2) * X2 ** 5.0 * lambda2
    
    return (3./13.) * (term1 + term2)
    
    
def get_tidal_phase(f: Array, theta: Array, kappa: float) -> Array:
    
    # Mass variables
    m1, m2, _, _, _, _ = theta 
    m1_s = m1 * gt
    m2_s = m2 * gt
    M_s = m1_s + m2_s
    eta = m1_s * m2_s / (M_s**2.0)

    # Compute ratios
    X1 = m1_s / M_s
    X2 = m2_s / M_s

    # Compute auxiliary quantities
    # TODO - not sure here about the factors
    M_omega = PI * f * (M_s)

    PN_x = M_omega ** (2.0/3.0)
    PN_x_2 = PN_x * PN_x
    PN_x_3over2 = PN_x ** (3.0/2.0)
    PN_x_5over2 = PN_x ** (5.0/2.0)

    c_Newt = 2.4375
    n_1 = -17.428
    n_3over2 = 31.867
    n_2 = -26.414
    n_5over2 = 62.362

    d_1 = n_1 - 2.496
    d_3over2 = 36.089

    # Get tidal phase
    tidal_phase = - kappa * c_Newt / (X1 * X2) * PN_x_5over2

    num = 1.0 + (n_1 * PN_x) + (n_3over2 * PN_x_3over2) + (n_2 * PN_x_2) + (n_5over2 * PN_x_5over2)
    den = 1.0 + (d_1 * PN_x) + (d_3over2 * PN_x_3over2)
    ratio = num / den
    
    # Complete result
    psi_T = - kappa * (39./(16. * eta)) * f ** (5./2.) * ratio
    
    return psi_T


def _compute_quadparam_octparam(lambda_: float) -> tuple[float, float]:
    """
    Computes quadparameter, see eq (28) of NRTidalv2 paper and also LALSimUniversalRelations.c of lalsuite
    Args:
        lambda_: tidal deformability

    Returns:
        quadparam: Quadrupole coefficient called C_Q in NRTidalv2 paper
        octparam: Octupole coefficient called C_Oc in NRTidalv2 paper
    """

    if 0 <= lambda_ <= 1:
        # Extension of the fit in the range lambda2 = [0,1.] so that the BH limit is enforced, lambda2bar->0 gives quadparam->1. and the junction with the universal relation is smooth, of class C2
        log_quadparam = 1. + lambda_ * (0.427688866723244 + lambda_ * (-0.324336526985068 + lambda_ * 0.1107439432180572))
    else:
        # Use universal relation
        log_lambda = jnp.log(lambda_)
        log_quadparam = 0.1940 + 0.09163 * log_lambda + 0.04812 * log_lambda ** 2. - 0.004286 * log_lambda ** 3 + 0.00012450 * log_lambda ** 4

    log_octparam = 0.003131 + 2.071 * log_quadparam - 0.7152 * log_quadparam ** 2 + 0.2458 * log_quadparam ** 3 - 0.03309 * log_quadparam ** 4

    # Get rid of log and remove 1 for BBH baseline
    quadparam = jnp.exp(log_quadparam) - 1
    octparam = jnp.exp(log_octparam) - 1

    return quadparam, octparam



def get_spin_phase_correction(f: Array, theta: Array) -> Array:
    
    m1, m2, chi1, chi2, lambda1, lambda2 = theta

    # Convert the mass variables
    m1_s = m1 * gt
    m2_s = m2 * gt
    M_s = m1_s + m2_s
    eta = m1_s * m2_s / (M_s**2.0)

    # Compute the auxiliary variables
    X1 = m1_s / M_s
    X2 = m2_s / M_s

    X1sq = X1 * X1
    X2sq = X2 * X2
    chi1_sq = chi1 * chi1
    chi2_sq = chi2 * chi2

    # Compute quadparam1
    quadparam1, octparam1 = _compute_quadparam_octparam(lambda1)
    quadparam2, octparam2 = _compute_quadparam_octparam(lambda2)

    SS_2  =  - 50. * quadparam1 * X1sq * chi1_sq
    SS_2  += - 50. * quadparam2 * X2sq * chi2_sq

    SS_3  =  (5. / 84.) * (9407. + 8218. * X1 - 2016. * X1 ** 2) * quadparam1 * X1 ** 2 * chi1 ** 2
    SS_3  += (5. / 84.) * (9407. + 8218. * X2 - 2016. * X2 ** 2) * quadparam2 * X2 ** 2 * chi2 ** 2

    # Following is taken from LAL source code
    SS_3p5 = - 400. * PI * (quadparam1 - 1.) * chi1_sq * X1sq - 400. * PI * (quadparam2 - 1.) * chi2_sq * X2sq
    SS_3p5 += 10.*((X1sq + 308./3. * X1) * chi1 + (X2 - 89./3. * X2) * chi2) * (quadparam1 - 1.) * X1sq * chi1_sq + 10.*((X2sq + 308./3. * X2) * chi2 + (X1sq - 89./3. * X1) * chi1) * (quadparam2 - 1.) * X2sq * chi2_sq - 440. * octparam1 * X1 * X1sq * chi1_sq * chi1 - 440. * octparam2 * X2 * X2sq * chi2_sq * chi2

    psi_SS = (3. / (128. * eta)) * (SS_2 * f ** (-1./2.) + SS_3 * f ** (1./2.) + SS_3p5 * f)

    # FIXME - these corrections are wrong, have to double check then remove this override
    # Override - making SS contribution zero
    psi_SS = jnp.zeros_like(f)

    return psi_SS
    
    
def get_tidal_amplitude(f: Array, theta: Array, kappa: float, dL: float =1):
    
    # Mass variables
    m1, m2, _, _, _, _ = theta 
    m1_s = m1 * gt
    m2_s = m2 * gt
    M_s = m1_s + m2_s
    eta = m1_s * m2_s / (M_s**2.0)
    
    # Build pade approximant

    M_sec   = (M_s * gt)

    prefac = 9.0 * kappa

    x = (PI * M_sec * f) ** (2.0/3.0)
    # ampT = 0.0
    # poly = 1.0
    n1   = 4.157407407407407
    n289 = 2519.111111111111
    d    = 13477.8073677

    poly = (1.0 + n1 * x + n289 * x ** 2.89) / (1 + d * x ** 4.)
    ampT = - prefac * x ** 3.25 * poly

    # Result
    # A_T = - ( (5. * PI * eta) / (24.)) ** (1. / 2.) * 9 * M_s**2  * kappa * f ** (13. / 4.) * pade
    dist_s = (dL * m_per_Mpc) / C
    return ampT / dist_s


def _get_merger_frequency(theta, kappa=None):
    
    # TODO - remove later on?
    
    # Already rescaled below in global function
    m1, m2, chi1, chi2, lambda1, lambda2 = theta 
    # Convert the mass variables
    m1_s = m1 * gt
    m2_s = m2 * gt
    M_s = m1_s + m2_s

    q = m1_s / m2_s

    X1 = m1_s / M_s
    X2 = m2_s / M_s

    # If kappa was not given, compute it
    if kappa is None:
        kappa = get_kappa(theta)
    
    a_0 = 0.3586
    n_1 = 3.35411203e-2
    n_2 = 4.31460284e-5
    d_1 = 7.54224145e-2
    d_2 = 2.23626859e-4

    kappa_sq = kappa ** 2.0
    num = 1.0 + n_1 * kappa + n_2 * kappa ** 2.0
    den = 1.0 + d_1 * kappa + d_2 * kappa ** 2.0
    Q_0 = a_0 * jnp.sqrt(X2 / X1)

    # Dimensionless angular frequency of merger
    Momega_merger = Q_0 * (num / den)

    # convert from angular frequency to frequency (divide by 2*pi) and then convert from dimensionless frequency to Hz (divide by mtot * LAL_MTSUN_SI)
    fHz_merger = Momega_merger / (M_s) / (2 * PI)

    return fHz_merger


# FIXME - what about the Planck taper? See Eq 25 of NRTidalv2 paper

def _planck_taper(t: Array, t1: float, t2: float) -> Array:
    """
    As taken from Lalsuite
    Args:
        t:
        t1:
        t2:

    Returns:
        Planck taper
    """

    # Middle part: transition formula for Planck taper
    middle = 1. / (jnp.exp((t2 - t1)/(t - t1) + (t2 - t1)/(t - t2)) + 1.)

    taper = jnp.heaviside(t1 - t, 1) * jnp.zeros_like(t) \
            + jnp.heaviside(t - t1, 1) * jnp.heaviside(t2 - t, 1) * middle \
            + jnp.heaviside(t - t2, 1) * jnp.ones_like(t)

    return taper

def get_planck_taper(f: Array, theta: Array, kappa: float):
    
    # Already rescaled below in global function
    # m1, m2, chi1, chi2, lambda1, lambda2 = theta
    # # Convert the mass variables
    # m1_s = m1 * gt
    # m2_s = m2 * gt
    # M_s = m1_s + m2_s
    # eta = m1_s * m2_s / (M_s**2.0)

    # Get the merger frequency
    f_merger = _get_merger_frequency(theta, kappa)

    f_start = f_merger
    f_end = 1.2 * f_merger

    A_P = _planck_taper(f, f_start, f_end)

    # Safety override -- not working for nonzero lambdas

    A_P = jnp.zeros_like(f)

    return A_P

def _gen_NRTidalv2(f: Array, theta_intrinsic: Array, theta_extrinsic: Array, h0_bbh: Array):

    m1, m2, chi1, chi2, lambda1, lambda2 = theta_intrinsic
    M_s = (m1 + m2) * gt

    # Compute auxiliary quantities like kappa
    kappa = get_kappa(theta=theta_intrinsic)

    # Get BBH amplitude and phase
    A_bbh = jnp.abs(h0_bbh)
    psi_bbh = h0_bbh / A_bbh

    # Get amplitude
    A_T = get_tidal_amplitude(f, theta_intrinsic, kappa, dL=theta_extrinsic[0])
    # TODO double check that using ones here is OK
    A_P = jnp.ones_like(f) - get_planck_taper(f, theta_intrinsic, kappa)

    # Get phase
    psi_T = get_tidal_phase(f * M_s, theta_intrinsic, kappa)
    # FIXME - get correct SS terms
    psi_SS = get_spin_phase_correction(f * M_s, theta_intrinsic)
    # ext_phase_contrib = 2.0 * PI * f * theta_extrinsic[1] - 2 * theta_extrinsic[2]
    h0 = A_P * (h0_bbh + A_T * jnp.exp(1j * - psi_bbh)) * jnp.exp(1.j * -(psi_T + psi_SS))

    ## Other way to compute waveforms -- gives wrong results?
    # A = A_P * (A_T + A_bbh)
    # psi = psi_bbh + psi_SS + psi_T
    # h0 = A * jnp.exp(1j *  psi)

    return h0

def gen_NRTidalv2(f: Array, params: Array, f_ref: float, IMRphenom: str) -> Array:
    """
    Generate NRTidalv2 frequency domain waveform following 1508.07253.
    vars array contains both intrinsic and extrinsic variables
    theta = [Mchirp, eta, chi1, chi2, D, tc, phic]
    Mchirp: Chirp mass of the system [solar masses]
    eta: Symmetric mass ratio [between 0.0 and 0.25]
    chi1: Dimensionless aligned spin of the primary object [between -1 and 1]
    chi2: Dimensionless aligned spin of the secondary object [between -1 and 1]
    lambda1: Dimensionless tidal deformability of primary object
    lambda2: Dimensionless tidal deformability of secondary object
    D: Luminosity distance to source [Mpc]
    tc: Time of coalesence. This only appears as an overall linear in f contribution to the phase
    phic: Phase of coalesence

    f_ref: Reference frequency for the waveform
    
    IMRphenom: string selecting the underlying BBH approximant

    Returns:
    --------
      h0 (array): Strain
    """
    
    # Get parameters
    m1, m2 = Mc_eta_to_ms(jnp.array([params[0], params[1]]))
    theta_intrinsic = jnp.array([m1, m2, params[2], params[3], params[4], params[5]])
    theta_extrinsic = params[6:]

    # Get the parameters that are passed to the BBH waveform, all except lambdas
    bbh_params = jnp.concatenate((jnp.array([params[0], params[1], params[2], params[3]]), theta_extrinsic))
    print(bbh_params)

    # TODO - make compatible with other waveforms as well
    if IMRphenom == "IMRPhenomD":
        from ripple.waveforms.IMRPhenomD import (
            gen_IMRPhenomD as bbh_waveform_generator,
        )
    else:
        print("IMRPhenom string not recognized")
        return jnp.zeros_like(f)

    # Generate BBH waveform strain and get its amplitude and phase
    h0_bbh = bbh_waveform_generator(f, bbh_params, f_ref)

    # Use BBH waveform and add tidal corrections
    return _gen_NRTidalv2(f, theta_intrinsic, theta_extrinsic, h0_bbh)


def gen_NRTidalv2_hphc(f: Array, params: Array, f_ref: float, IMRphenom: str="IMRPhenomD"):
    """
    vars array contains both intrinsic and extrinsic variables
    
    theta = [Mchirp, eta, chi1, chi2, lambda1, lambda2, D, tc, phic, inclination]
    Mchirp: Chirp mass of the system [solar masses]
    eta: Symmetric mass ratio [between 0.0 and 0.25]
    chi1: Dimensionless aligned spin of the primary object [between -1 and 1]
    chi2: Dimensionless aligned spin of the secondary object [between -1 and 1]
    D: Luminosity distance to source [Mpc]
    tc: Time of coalesence. This only appears as an overall linear in f contribution to the phase
    phic: Phase of coalesence
    inclination: Inclination angle of the binary [between 0 and PI]

    f_ref: Reference frequency for the waveform

    Returns:
    --------
      hp (array): Strain of the plus polarization
      hc (array): Strain of the cross polarization
    """
    iota = params[-1]
    print(iota)
    h0 = gen_NRTidalv2(f, params[:-1], f_ref, IMRphenom=IMRphenom)
    
    hp = h0 * (1 / 2 * (1 + jnp.cos(iota) ** 2))
    hc = -1j * h0 * jnp.cos(iota)

    return hp, hc
