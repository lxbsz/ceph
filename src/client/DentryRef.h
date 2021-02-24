// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

#ifndef CEPH_CLIENT_DENTRYREF_H
#define CEPH_CLIENT_DENTRYREF_H

#include <boost/intrusive_ptr.hpp>
class Dentry;
void intrusive_ptr_add_ref(Dentry *dn);
void intrusive_ptr_release(Dentry *dn);
typedef boost::intrusive_ptr<Dentry> DentryRef;
#endif
